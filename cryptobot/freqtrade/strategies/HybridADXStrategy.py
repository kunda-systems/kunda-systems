"""
HybridADXStrategy - Compartiment B (Le Moteur)
================================================
Stratégie hybride avec détection automatique du régime de marché via ADX.

Régimes :
  - ADX < 20  → Grid Bot (range market) : accumulation dans une fourchette de prix
  - ADX > 30  → Momentum (tendance) : EMA crossover + RSI
  - ADX 20-30 → Hybride progressif : pondération variable des deux approches

Paires tradées : BTC/USDT (40%), ETH/USDT (35%), SOL/USDT (25%)
Capital Compartiment B : ~500€ | Stop global : -40% → pause automatique
"""

from datetime import datetime
from functools import reduce
from typing import Optional

import numpy as np
import pandas as pd
import talib.abstract as ta
from freqtrade.persistence import Trade
from freqtrade.strategy import (
    DecimalParameter,
    IntParameter,
    IStrategy,
    merge_informative_pair,
)
from pandas import DataFrame


class HybridADXStrategy(IStrategy):
    """
    Stratégie hybride ADX / Grid / Momentum pour le Compartiment B.
    """

    INTERFACE_VERSION = 3

    # ── Timeframe ──────────────────────────────────────────────────────────────
    timeframe = "1h"
    informative_timeframe = "4h"  # pour confirmation de tendance

    # ── Paramètres de risque ───────────────────────────────────────────────────
    stoploss = -0.08          # Stop-loss par trade : -8%
    trailing_stop = True
    trailing_stop_positive = 0.03
    trailing_stop_positive_offset = 0.05
    trailing_only_offset_is_reached = True

    # ── Multiple entrées (DCA dans le trade) ──────────────────────────────────
    max_entry_position_adjustment = 3  # 3 DCA max par trade
    position_adjustment_enable = True

    # ── Paramètres optimisables (via hyperopt) ─────────────────────────────────
    # ADX thresholds
    adx_range_threshold = IntParameter(15, 25, default=20, space="buy", optimize=True)
    adx_trend_threshold = IntParameter(25, 40, default=30, space="buy", optimize=True)

    # Grid Bot parameters
    grid_spacing = DecimalParameter(0.01, 0.05, default=0.025, space="buy", optimize=True)
    grid_levels = IntParameter(3, 8, default=5, space="buy", optimize=True)

    # Momentum parameters
    ema_fast = IntParameter(8, 21, default=12, space="buy", optimize=True)
    ema_slow = IntParameter(21, 55, default=34, space="buy", optimize=True)
    rsi_buy = IntParameter(30, 55, default=45, space="buy", optimize=True)
    rsi_sell = IntParameter(55, 80, default=65, space="sell", optimize=True)

    # ── ROI (take profit dynamique) ────────────────────────────────────────────
    minimal_roi = {
        "0":   0.08,   # 8% dès l'entrée
        "60":  0.05,   # 5% après 1h
        "120": 0.03,   # 3% après 2h
        "240": 0.01,   # 1% après 4h
    }

    # ── Startup candles ────────────────────────────────────────────────────────
    startup_candle_count: int = 100

    # ── Plots ──────────────────────────────────────────────────────────────────
    plot_config = {
        "main_plot": {
            "ema_fast": {"color": "blue"},
            "ema_slow": {"color": "orange"},
            "bb_upper": {"color": "grey", "type": "line"},
            "bb_lower": {"color": "grey", "type": "line"},
        },
        "subplots": {
            "ADX": {
                "adx": {"color": "red"},
                "adx_range_threshold": {"color": "green"},
                "adx_trend_threshold": {"color": "orange"},
            },
            "RSI": {
                "rsi": {"color": "purple"},
            },
            "Regime": {
                "regime": {"color": "blue"},
            },
        },
    }

    def informative_pairs(self):
        """Paires pour données 4h (confirmation tendance)."""
        pairs = self.dp.current_whitelist()
        return [(pair, self.informative_timeframe) for pair in pairs]

    def populate_informative_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Indicateurs sur timeframe 4h pour confirmation de tendance."""
        dataframe["adx_4h"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["ema_50_4h"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema_200_4h"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["rsi_4h"] = ta.RSI(dataframe, timeperiod=14)
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Calcul de tous les indicateurs techniques."""

        # ── ADX (détection régime) ─────────────────────────────────────────────
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["plus_di"] = ta.PLUS_DI(dataframe, timeperiod=14)
        dataframe["minus_di"] = ta.MINUS_DI(dataframe, timeperiod=14)

        # ── ATR (volatilité, pour le grid spacing dynamique) ──────────────────
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]

        # ── EMA (momentum) ─────────────────────────────────────────────────────
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=self.ema_fast.value)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=self.ema_slow.value)
        dataframe["ema_200"] = ta.EMA(dataframe, timeperiod=200)

        # ── RSI ─────────────────────────────────────────────────────────────────
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["rsi_fast"] = ta.RSI(dataframe, timeperiod=7)

        # ── Bollinger Bands (pour le grid) ─────────────────────────────────────
        bollinger = ta.BBANDS(dataframe, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
        dataframe["bb_upper"] = bollinger["upperband"]
        dataframe["bb_mid"] = bollinger["middleband"]
        dataframe["bb_lower"] = bollinger["lowerband"]
        dataframe["bb_width"] = (dataframe["bb_upper"] - dataframe["bb_lower"]) / dataframe["bb_mid"]
        dataframe["bb_pct"] = (dataframe["close"] - dataframe["bb_lower"]) / (
            dataframe["bb_upper"] - dataframe["bb_lower"]
        )

        # ── MACD ────────────────────────────────────────────────────────────────
        macd = ta.MACD(dataframe)
        dataframe["macd"] = macd["macd"]
        dataframe["macd_signal"] = macd["macdsignal"]
        dataframe["macd_hist"] = macd["macdhist"]

        # ── Volume ──────────────────────────────────────────────────────────────
        dataframe["volume_mean"] = dataframe["volume"].rolling(window=20).mean()
        dataframe["volume_ratio"] = dataframe["volume"] / dataframe["volume_mean"]

        # ── Régime de marché ──────────────────────────────────────────────────
        # 0 = range (grid), 1 = trend (momentum), 0.5 = hybrid
        conditions_range = dataframe["adx"] < self.adx_range_threshold.value
        conditions_trend = dataframe["adx"] > self.adx_trend_threshold.value
        dataframe["regime"] = np.where(
            conditions_trend, 1.0,
            np.where(conditions_range, 0.0, 0.5)
        )

        # ── Merge données 4h ──────────────────────────────────────────────────
        informative = self.dp.get_pair_dataframe(
            pair=metadata["pair"], timeframe=self.informative_timeframe
        )
        if not informative.empty:
            informative = self.populate_informative_indicators(informative, metadata)
            dataframe = merge_informative_pair(
                dataframe, informative, self.timeframe, self.informative_timeframe,
                ffill=True
            )

        return dataframe

    # ──────────────────────────────────────────────────────────────────────────
    # SIGNAUX D'ACHAT
    # ──────────────────────────────────────────────────────────────────────────

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Génère les signaux d'entrée selon le régime de marché détecté."""

        # ── Signal GRID BOT (ADX < seuil range) ──────────────────────────────
        grid_entry = (
            (dataframe["regime"] == 0.0)                   # marché latéral
            & (dataframe["bb_pct"] < 0.2)                  # proche du bas des BB
            & (dataframe["rsi"] < 45)                      # RSI pas suracheté
            & (dataframe["volume_ratio"] > 0.8)            # volume acceptable
            & (dataframe["close"] > dataframe["ema_200"])  # au-dessus de la MA long terme
        )

        # ── Signal MOMENTUM (ADX > seuil tendance) ───────────────────────────
        momentum_entry = (
            (dataframe["regime"] == 1.0)                              # marché directionnel
            & (dataframe["ema_fast"] > dataframe["ema_slow"])         # croisement haussier EMA
            & (dataframe["ema_fast"].shift(1) <= dataframe["ema_slow"].shift(1))  # signal frais
            & (dataframe["rsi"] > self.rsi_buy.value)                 # RSI en zone achat
            & (dataframe["rsi"] < 70)                                 # pas suracheté
            & (dataframe["macd"] > dataframe["macd_signal"])          # MACD positif
            & (dataframe["plus_di"] > dataframe["minus_di"])          # DI+ dominant
            & (dataframe["volume_ratio"] > 1.2)                       # volume fort
        )

        # ── Signal HYBRIDE (ADX zone transition 20-30) ───────────────────────
        hybrid_entry = (
            (dataframe["regime"] == 0.5)                              # zone de transition
            & (dataframe["bb_pct"] < 0.3)                             # proche bas BB
            & (dataframe["ema_fast"] > dataframe["ema_slow"])         # tendance EMA haussière
            & (dataframe["rsi"] > 40)
            & (dataframe["rsi"] < 60)
            & (dataframe["volume_ratio"] > 1.0)
        )

        # ── Confirmation 4h (si données disponibles) ─────────────────────────
        confirmation_4h = (
            dataframe.get("ema_50_4h_4h", dataframe["close"]) < dataframe["close"]
        ) | (
            dataframe.get("rsi_4h_4h", pd.Series(50, index=dataframe.index)) < 65
        )

        dataframe.loc[
            (grid_entry | momentum_entry | hybrid_entry) & confirmation_4h,
            "enter_long"
        ] = 1

        # Tag du signal pour analyse post-trade
        dataframe.loc[grid_entry & confirmation_4h, "enter_tag"] = "grid"
        dataframe.loc[momentum_entry & confirmation_4h, "enter_tag"] = "momentum"
        dataframe.loc[hybrid_entry & confirmation_4h, "enter_tag"] = "hybrid"

        return dataframe

    # ──────────────────────────────────────────────────────────────────────────
    # SIGNAUX DE VENTE
    # ──────────────────────────────────────────────────────────────────────────

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Génère les signaux de sortie."""

        # ── Sortie GRID BOT ───────────────────────────────────────────────────
        grid_exit = (
            (dataframe["regime"] == 0.0)
            & (dataframe["bb_pct"] > 0.8)           # proche du haut des BB
            & (dataframe["rsi"] > 60)
        )

        # ── Sortie MOMENTUM ───────────────────────────────────────────────────
        momentum_exit = (
            (dataframe["regime"] == 1.0)
            & (
                (dataframe["ema_fast"] < dataframe["ema_slow"])   # croisement baissier
                | (dataframe["rsi"] > self.rsi_sell.value)         # RSI suracheté
                | (dataframe["macd"] < dataframe["macd_signal"])   # MACD bearish
            )
        )

        # ── Sortie HYBRIDE ────────────────────────────────────────────────────
        hybrid_exit = (
            (dataframe["regime"] == 0.5)
            & (dataframe["bb_pct"] > 0.7)
            & (dataframe["rsi"] > 62)
        )

        dataframe.loc[
            grid_exit | momentum_exit | hybrid_exit,
            "exit_long"
        ] = 1

        return dataframe

    # ──────────────────────────────────────────────────────────────────────────
    # DCA ADAPTATIF (Ajustement de position)
    # ──────────────────────────────────────────────────────────────────────────

    def adjust_trade_position(
        self,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        min_stake: Optional[float],
        max_stake: float,
        current_entry_rate: float,
        current_exit_rate: float,
        current_entry_profit: float,
        current_exit_profit: float,
        **kwargs,
    ) -> Optional[float]:
        """
        DCA adaptatif dans le trade :
        - Renforce si le prix baisse de N% (grid spacing)
        - Maximum 3 renforts
        """
        # Ne pas DCA si plus de 3 ajustements
        if trade.nr_of_successful_entries >= self.max_entry_position_adjustment:
            return None

        # Calcul du spacing dynamique basé sur l'ATR
        dataframe, _ = self.dp.get_analyzed_dataframe(trade.pair, self.timeframe)
        if dataframe.empty:
            return None

        last_candle = dataframe.iloc[-1]
        atr_pct = last_candle.get("atr_pct", self.grid_spacing.value)

        # DCA niveaux selon le nombre d'entrées déjà effectuées
        dca_triggers = {
            1: -(atr_pct * 1.5),    # Premier renfort : -1.5 ATR
            2: -(atr_pct * 3.0),    # Deuxième renfort : -3 ATR
            3: -(atr_pct * 5.0),    # Troisième renfort : -5 ATR
        }

        next_dca = trade.nr_of_successful_entries + 1
        trigger = dca_triggers.get(next_dca)

        if trigger and current_profit <= trigger:
            # Mise au DCA : même taille que la mise initiale
            stake_amount = trade.stake_amount
            if stake_amount > max_stake:
                stake_amount = max_stake
            return stake_amount

        return None

    # ──────────────────────────────────────────────────────────────────────────
    # STOP-LOSS PERSONNALISÉ
    # ──────────────────────────────────────────────────────────────────────────

    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        after_fill: bool,
        **kwargs,
    ) -> float:
        """
        Stop-loss adaptatif selon le régime de marché.
        Grid : plus serré. Momentum : plus large pour laisser courir.
        """
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty:
            return self.stoploss

        last_candle = dataframe.iloc[-1]
        regime = last_candle.get("regime", 0.5)
        atr_pct = last_candle.get("atr_pct", 0.02)

        if regime == 0.0:       # Grid : stop serré
            sl = -(atr_pct * 2.5)
        elif regime == 1.0:     # Momentum : stop large
            sl = -(atr_pct * 4.0)
        else:                   # Hybride
            sl = -(atr_pct * 3.0)

        return max(sl, -0.15)  # Ne jamais dépasser -15% sur un seul trade

    # ──────────────────────────────────────────────────────────────────────────
    # TAILLE DE POSITION
    # ──────────────────────────────────────────────────────────────────────────

    def custom_entry_price(
        self,
        pair: str,
        trade: Optional[Trade],
        current_time: datetime,
        proposed_rate: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        """
        Prix d'entrée légèrement sous le marché pour le grid bot.
        Pour le momentum : entrée au marché.
        """
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty:
            return proposed_rate

        last_candle = dataframe.iloc[-1]
        regime = last_candle.get("regime", 0.5)
        atr_pct = last_candle.get("atr_pct", 0.005)

        if regime == 0.0 and entry_tag == "grid":
            # Grid : essayer d'acheter 0.3% en dessous du prix actuel
            return proposed_rate * (1 - min(atr_pct * 0.5, 0.003))

        return proposed_rate  # Momentum et hybride : au marché
