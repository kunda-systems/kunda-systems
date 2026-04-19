"""
DCAStrategy - Compartiment A (Le Coffre)
=========================================
Stratégie DCA (Dollar Cost Averaging) pour l'accumulation long terme.

Allocation : BTC 60% / ETH 40%
Fréquence  : 1 achat par mois (+ gains du Compartiment B)
DCA renforcé : si drawdown > 30% depuis ATH, doublement automatique de la mise

Ce fichier est utilisé comme stratégie Freqtrade pour simuler le DCA.
En production, c'est n8n qui déclenche les achats via le script dca_execute.py.
"""

from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import talib.abstract as ta
from freqtrade.persistence import Trade
from freqtrade.strategy import DecimalParameter, IntParameter, IStrategy
from pandas import DataFrame


class DCAStrategy(IStrategy):
    """
    Stratégie DCA simple pour le Compartiment A.
    Achète BTC et ETH périodiquement, avec renforcement sur drawdown.
    """

    INTERFACE_VERSION = 3

    timeframe = "1d"  # Timeframe journalier pour le DCA

    # ── Pas de stop-loss pour l'accumulation long terme ───────────────────────
    stoploss = -0.99       # Pratiquement pas de stop (philosophie accumulation)
    trailing_stop = False

    # ── ROI minimal : on ne vend JAMAIS en DCA (accumulation pure) ───────────
    # Les sorties sont gérées manuellement / par n8n uniquement
    minimal_roi = {
        "0": 100.0  # 10000% → ne se déclenchera jamais en pratique
    }

    # ── Paramètres ────────────────────────────────────────────────────────────
    # Seuil de drawdown pour renforcement
    drawdown_threshold = DecimalParameter(
        0.20, 0.50, default=0.30, space="buy", optimize=False
    )
    # Multiplicateur du DCA renforcé
    dca_boost_multiplier = DecimalParameter(
        1.5, 3.0, default=2.0, space="buy", optimize=False
    )

    startup_candle_count: int = 365  # 1 an pour calculer l'ATH

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Indicateurs pour le DCA : ATH sur fenêtre glissante et drawdown."""

        # ATH sur les 365 derniers jours
        dataframe["ath_365d"] = dataframe["high"].rolling(window=365, min_periods=30).max()

        # Drawdown depuis l'ATH
        dataframe["drawdown_from_ath"] = (
            (dataframe["close"] - dataframe["ath_365d"]) / dataframe["ath_365d"]
        )

        # EMA 200 jours (filtre de tendance long terme)
        dataframe["ema_200"] = ta.EMA(dataframe, timeperiod=200)

        # RSI 14 jours
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)

        # Mois courant (pour limiter à 1 achat par mois)
        dataframe["month"] = pd.to_datetime(dataframe["date"]).dt.month
        dataframe["year"] = pd.to_datetime(dataframe["date"]).dt.year

        # Indicateur de zone de drawdown sévère
        dataframe["in_drawdown"] = (
            dataframe["drawdown_from_ath"] < -self.drawdown_threshold.value
        ).astype(int)

        # Facteur de boost DCA
        dataframe["dca_multiplier"] = np.where(
            dataframe["in_drawdown"] == 1,
            self.dca_boost_multiplier.value,
            1.0
        )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Signal d'achat DCA : une fois par mois, à la première bougie du mois.
        Si drawdown > 30% : signal de renforcement.
        """
        # Premier jour du mois = achat DCA régulier
        dataframe["is_first_of_month"] = (
            pd.to_datetime(dataframe["date"]).dt.day == 1
        ).astype(int)

        # Signal d'achat : premier du mois OU drawdown sévère (1x/semaine max)
        is_monday = pd.to_datetime(dataframe["date"]).dt.dayofweek == 0

        regular_dca = dataframe["is_first_of_month"] == 1

        boosted_dca = (
            (dataframe["in_drawdown"] == 1)
            & is_monday
            & (dataframe["rsi"] < 45)  # Confirme que ce n'est pas un rebond temporaire
        )

        dataframe.loc[regular_dca, "enter_long"] = 1
        dataframe.loc[regular_dca, "enter_tag"] = "dca_regular"

        dataframe.loc[boosted_dca & ~regular_dca, "enter_long"] = 1
        dataframe.loc[boosted_dca & ~regular_dca, "enter_tag"] = "dca_boosted"

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Pas de vente automatique en DCA.
        Les sorties sont uniquement manuelles (après 24 mois minimum).
        """
        dataframe["exit_long"] = 0
        return dataframe

    def custom_stake_amount(
        self,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: Optional[float],
        max_stake: float,
        leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        """
        Taille de mise adaptée :
        - DCA normal : mise standard (définie dans config)
        - DCA renforcé : 2x la mise standard si drawdown > 30%
        """
        dataframe, _ = self.dp.get_analyzed_dataframe(
            kwargs.get("pair", "BTC/USDT"), self.timeframe
        )

        if not dataframe.empty:
            last_candle = dataframe.iloc[-1]
            multiplier = last_candle.get("dca_multiplier", 1.0)

            if entry_tag == "dca_boosted":
                stake = proposed_stake * multiplier
                return min(stake, max_stake)

        return proposed_stake
