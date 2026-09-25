"""
====================================================================
NSE 09:45 LIVE SHORT-BIASED SCANNER
====================================================================

LIVE-ONLY VERSION
-----------------

This version is designed for:

    GitHub Actions
        ->
    Python scanner
        ->
    Telegram notification

There is NO:
    - interactive menu
    - historical mode
    - date input
    - backtest mode
    - historical trade evaluation

The program automatically uses today's date in Asia/Kolkata.

DECISION POINT
--------------

09:15 - 09:30
09:30 - 09:45

Signal is generated after the 09:45 candle.

FEATURES
--------

- Historical indicator warm-up
- Session VWAP
- Same-time-of-day relative volume
- NIFTY 50 relative strength
- ATR normalization
- EMA9 / EMA20
- RSI
- MACD
- Candle structure
- Momentum
- Exhaustion model
- Liquidity filter
- Short-biased scoring
- Telegram alerts

IMPORTANT
---------

This is a RESEARCH / SCANNING SYSTEM.

It does not guarantee future returns.

Yahoo Finance intraday data is not institutional-grade NSE
execution data and should be replaced with a reliable data
provider for serious production research/trading.

====================================================================
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import yfinance as yf


# ====================================================================
# CONFIGURATION
# ====================================================================

MARKET_TZ = "Asia/Kolkata"

MARKET_OPEN = "09:15"
OPENING_END = "09:30"
DECISION_TIME = "09:45"
MARKET_CLOSE = "15:30"

SIGNAL_INTERVAL = "15m"

NIFTY50_TICKER = "^NSEI"

# Historical warm-up required for EMA/RSI/MACD/ATR.
WARMUP_DAYS = 45

# Relative-volume historical sample.
RVOL_LOOKBACK_DAYS = 20

MIN_RVOL_OBSERVATIONS = 8


# ====================================================================
# NSE UNIVERSE
# ====================================================================

NIFTY_500_URL = (
    "https://nsearchives.nseindia.com/content/indices/"
    "ind_nifty500list.csv"
)

NIFTY_50_URL = (
    "https://nsearchives.nseindia.com/content/indices/"
    "ind_nifty50list.csv"
)

EXCLUDE_NIFTY50 = True


# ====================================================================
# LIQUIDITY
# ====================================================================

MIN_TURNOVER_CR = 50.0


# ====================================================================
# INDICATORS
# ====================================================================

EMA_FAST = 9
EMA_SLOW = 20

RSI_PERIOD = 14

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

ATR_PERIOD = 14


# ====================================================================
# SHORT SIGNAL
# ====================================================================

SHORT_TRADEABLE_SCORE = 60.0

SHORT_HIGH_CONVICTION_SCORE = 75.0

MIN_SHORT_TOTAL_MOVE = 0.30

MIN_OPENING_SHORT_MOVE = 0.25


# ====================================================================
# EXHAUSTION
# ====================================================================

RSI_OVERSOLD = 30.0

RSI_EXTREME_OVERSOLD = 22.0

MAX_SHORT_VWAP_DISTANCE = 3.0

MAX_SHORT_EMA20_DISTANCE = 3.5

MAX_OPENING_COLLAPSE = 3.0


# ====================================================================
# DOWNLOAD
# ====================================================================

BATCH_SIZE = 40

DOWNLOAD_TIMEOUT = 20

BATCH_DELAY = 0.8

MAX_DOWNLOAD_RETRIES = 3


# ====================================================================
# TELEGRAM
# ====================================================================

TELEGRAM_API_BASE = (
    "https://api.telegram.org/bot"
)


# ====================================================================
# RESULTS
# ====================================================================

TOP_SHORTS_TO_SEND = 5

EXPORT_RESULTS = True

EXPORT_FILENAME = (
    "nse_0945_live_results.csv"
)


# ====================================================================
# COST MODEL
# ====================================================================

ROUND_TRIP_COST_PCT = 0.10

SLIPPAGE_PER_SIDE_PCT = 0.05

TOTAL_SLIPPAGE_PCT = (
    SLIPPAGE_PER_SIDE_PCT * 2
)

TOTAL_COST_PCT = (
    ROUND_TRIP_COST_PCT
    +
    TOTAL_SLIPPAGE_PCT
)


# ====================================================================
# TELEGRAM CREDENTIALS
# ====================================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN"
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID"
)


# ====================================================================
# TERMINAL
# ====================================================================

def clear_line() -> None:

    sys.stdout.write(
        "\r\033[2K"
    )

    sys.stdout.flush()


def progress_line(
    message: str
) -> None:

    sys.stdout.write(
        "\r\033[2K" + message
    )

    sys.stdout.flush()


# ====================================================================
# DATE / TIME
# ====================================================================

def get_current_ist() -> pd.Timestamp:

    return pd.Timestamp.now(
        tz=MARKET_TZ
    )


def get_target_date() -> pd.Timestamp:

    now = get_current_ist()

    return (
        now
        .tz_localize(None)
        .normalize()
    )


# ====================================================================
# TELEGRAM
# ====================================================================

def telegram_enabled() -> bool:

    return bool(
        TELEGRAM_BOT_TOKEN
        and TELEGRAM_CHAT_ID
    )


def send_telegram_message(
    message: str
) -> bool:

    if not telegram_enabled():

        print(
            "WARNING: Telegram credentials "
            "are not configured."
        )

        return False

    url = (
        TELEGRAM_API_BASE
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    payload = {

        "chat_id":
            TELEGRAM_CHAT_ID,

        "text":
            message,

        "parse_mode":
            "HTML",

        "disable_web_page_preview":
            True,
    }

    try:

        response = requests.post(

            url,

            json=payload,

            timeout=20,
        )

        response.raise_for_status()

        data = response.json()

        if not data.get("ok", False):

            print(
                "Telegram API returned failure:"
            )

            print(data)

            return False

        print(
            "Telegram notification sent."
        )

        return True

    except Exception as exc:

        print(
            f"Telegram error: {exc}"
        )

        return False


# ====================================================================
# NSE CSV
# ====================================================================

def download_nse_csv(
    url: str
) -> pd.DataFrame:

    headers = {

        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "Chrome/131.0 Safari/537.36"
        ),

        "Accept": (
            "text/csv,application/csv,"
            "application/octet-stream,*/*"
        ),

        "Referer":
            "https://www.nseindia.com/",
    }

    response = requests.get(

        url,

        headers=headers,

        timeout=30,
    )

    response.raise_for_status()

    return pd.read_csv(
        io.BytesIO(
            response.content
        )
    )


def find_symbol_column(
    df: pd.DataFrame
) -> str:

    candidates = [

        "Symbol",

        "SYMBOL",

        "symbol",

        "Ticker",

        "TICKER",
    ]

    for column in candidates:

        if column in df.columns:

            return column

    raise ValueError(
        "Could not find NSE symbol column."
    )


def get_index_symbols(
    url: str
) -> set[str]:

    df = download_nse_csv(
        url
    )

    column = find_symbol_column(
        df
    )

    symbols = (

        df[column]

        .dropna()

        .astype(str)

        .str.strip()

        .str.upper()
    )

    return set(symbols)


def build_universe() -> List[str]:

    print(
        "Downloading NSE universe..."
    )

    nifty500 = get_index_symbols(
        NIFTY_500_URL
    )

    print(
        f"NIFTY 500 symbols: "
        f"{len(nifty500)}"
    )

    if EXCLUDE_NIFTY50:

        nifty50 = get_index_symbols(
            NIFTY_50_URL
        )

        symbols = (
            nifty500
            -
            nifty50
        )

        print(
            f"NIFTY 50 excluded: "
            f"{len(nifty50)}"
        )

    else:

        symbols = nifty500

    tickers = [

        f"{symbol}.NS"

        for symbol in sorted(symbols)

        if symbol
    ]

    print(
        f"Final universe: "
        f"{len(tickers)} stocks"
    )

    return tickers


# ====================================================================
# YFINANCE
# ====================================================================

def yf_download_quiet(
    *args,
    **kwargs
) -> pd.DataFrame:

    stdout = io.StringIO()

    stderr = io.StringIO()

    for attempt in range(
        1,
        MAX_DOWNLOAD_RETRIES + 1
    ):

        try:

            with contextlib.redirect_stdout(
                stdout
            ), contextlib.redirect_stderr(
                stderr
            ):

                result = yf.download(
                    *args,
                    **kwargs
                )

            if result is None:

                result = pd.DataFrame()

            if not result.empty:

                return result

        except Exception as exc:

            print(
                f"Yahoo download attempt "
                f"{attempt} failed: {exc}"
            )

        if attempt < MAX_DOWNLOAD_RETRIES:

            time.sleep(
                2 * attempt
            )

    return pd.DataFrame()


# ====================================================================
# DATA CLEANING
# ====================================================================

def flatten_columns(
    df: pd.DataFrame
) -> pd.DataFrame:

    if isinstance(
        df.columns,
        pd.MultiIndex
    ):

        df.columns = (
            df.columns
            .get_level_values(0)
        )

    return df


def normalize_intraday_index(
    df: pd.DataFrame
) -> pd.DataFrame:

    if df.empty:

        return df

    df = df.copy()

    df.index = pd.to_datetime(
        df.index
    )

    if getattr(
        df.index,
        "tz",
        None
    ) is not None:

        df.index = (
            df.index
            .tz_convert(
                MARKET_TZ
            )
        )

    else:

        df.index = (
            df.index
            .tz_localize(
                MARKET_TZ
            )
        )

    return df.sort_index()


def clean_ticker_data(
    df: pd.DataFrame
) -> pd.DataFrame:

    if (
        df is None
        or df.empty
    ):

        return pd.DataFrame()

    df = df.copy()

    df = flatten_columns(
        df
    )

    required = [

        "Open",

        "High",

        "Low",

        "Close",

        "Volume",
    ]

    for column in required:

        if column not in df.columns:

            return pd.DataFrame()

    df = df[
        required
    ].copy()

    df = normalize_intraday_index(
        df
    )

    for column in required:

        df[column] = pd.to_numeric(

            df[column],

            errors="coerce"
        )

    df = df.dropna(
        subset=required
    )

    df = df[

        (df["Open"] > 0)

        & (df["High"] > 0)

        & (df["Low"] > 0)

        & (df["Close"] > 0)

        & (df["High"] >= df["Low"])
    ]

    return df.sort_index()


# ====================================================================
# DOWNLOAD 15-MINUTE DATA
# ====================================================================

def download_intraday_batch(
    tickers: List[str],
    target_date: pd.Timestamp
) -> Dict[str, pd.DataFrame]:

    start_date = (
        target_date
        -
        pd.Timedelta(
            days=WARMUP_DAYS
        )
    )

    # Add one extra calendar day because Yahoo's end
    # parameter is exclusive.
    end_date = (
        target_date
        +
        pd.Timedelta(
            days=1
        )
    )

    raw = yf_download_quiet(

        tickers,

        start=start_date.strftime(
            "%Y-%m-%d"
        ),

        end=end_date.strftime(
            "%Y-%m-%d"
        ),

        interval=SIGNAL_INTERVAL,

        group_by="ticker",

        auto_adjust=False,

        prepost=False,

        progress=False,

        threads=True,

        ignore_tz=False,

        timeout=DOWNLOAD_TIMEOUT,

        multi_level_index=True,
    )

    if raw.empty:

        return {}

    results: Dict[
        str,
        pd.DataFrame
    ] = {}

    if isinstance(
        raw.columns,
        pd.MultiIndex
    ):

        level0 = set(

            raw.columns
            .get_level_values(0)
        )

        for ticker in tickers:

            if ticker not in level0:

                continue

            try:

                ticker_df = raw[
                    ticker
                ].copy()

                ticker_df = clean_ticker_data(
                    ticker_df
                )

                if not ticker_df.empty:

                    results[
                        ticker
                    ] = ticker_df

            except Exception:

                continue

    elif len(tickers) == 1:

        ticker_df = clean_ticker_data(
            raw
        )

        if not ticker_df.empty:

            results[
                tickers[0]
            ] = ticker_df

    return results


# ====================================================================
# SESSION
# ====================================================================

def filter_session(
    df: pd.DataFrame,
    target_date: pd.Timestamp
) -> pd.DataFrame:

    if df.empty:

        return df

    date_str = (
        target_date.strftime(
            "%Y-%m-%d"
        )
    )

    session_open = pd.Timestamp(

        f"{date_str} "
        f"{MARKET_OPEN}",

        tz=MARKET_TZ
    )

    session_close = pd.Timestamp(

        f"{date_str} "
        f"{MARKET_CLOSE}",

        tz=MARKET_TZ
    )

    return df[

        (df.index >= session_open)

        & (df.index < session_close)

    ].sort_index()


# ====================================================================
# VWAP
# ====================================================================

def calculate_session_vwap(
    df: pd.DataFrame
) -> pd.Series:

    typical_price = (

        df["High"]

        + df["Low"]

        + df["Close"]

    ) / 3.0

    cumulative_pv = (

        typical_price
        *
        df["Volume"]
    ).cumsum()

    cumulative_volume = (
        df["Volume"]
        .cumsum()
    )

    return (

        cumulative_pv

        /

        cumulative_volume.replace(
            0,
            np.nan
        )
    )


# ====================================================================
# RSI
# ====================================================================

def calculate_rsi(
    close: pd.Series,
    period: int = RSI_PERIOD
) -> pd.Series:

    delta = close.diff()

    gain = delta.clip(
        lower=0
    )

    loss = -delta.clip(
        upper=0
    )

    avg_gain = (

        gain

        .ewm(

            alpha=1 / period,

            adjust=False,

            min_periods=period
        )

        .mean()
    )

    avg_loss = (

        loss

        .ewm(

            alpha=1 / period,

            adjust=False,

            min_periods=period
        )

        .mean()
    )

    rs = (

        avg_gain

        /

        avg_loss.replace(
            0,
            np.nan
        )
    )

    rsi = (

        100

        -

        100 / (1 + rs)
    )

    rsi = rsi.where(
        avg_loss != 0,
        100
    )

    return rsi


# ====================================================================
# MACD
# ====================================================================

def calculate_macd(
    close: pd.Series
) -> Tuple[
    pd.Series,
    pd.Series,
    pd.Series
]:

    ema_fast = (

        close

        .ewm(

            span=MACD_FAST,

            adjust=False,

            min_periods=MACD_FAST
        )

        .mean()
    )

    ema_slow = (

        close

        .ewm(

            span=MACD_SLOW,

            adjust=False,

            min_periods=MACD_SLOW
        )

        .mean()
    )

    macd = (
        ema_fast
        -
        ema_slow
    )

    signal = (

        macd

        .ewm(

            span=MACD_SIGNAL,

            adjust=False,

            min_periods=MACD_SIGNAL
        )

        .mean()
    )

    histogram = (
        macd
        -
        signal
    )

    return (
        macd,
        signal,
        histogram
    )


# ====================================================================
# ATR
# ====================================================================

def calculate_atr(
    df: pd.DataFrame,
    period: int = ATR_PERIOD
) -> pd.Series:

    previous_close = (
        df["Close"]
        .shift(1)
    )

    tr1 = (
        df["High"]
        -
        df["Low"]
    )

    tr2 = (
        df["High"]
        -
        previous_close
    ).abs()

    tr3 = (
        df["Low"]
        -
        previous_close
    ).abs()

    true_range = pd.concat(

        [
            tr1,
            tr2,
            tr3,
        ],

        axis=1

    ).max(
        axis=1
    )

    return (

        true_range

        .ewm(

            alpha=1 / period,

            adjust=False,

            min_periods=period
        )

        .mean()
    )


# ====================================================================
# HISTORICAL INDICATORS
# ====================================================================

def add_historical_indicators(
    df: pd.DataFrame
) -> pd.DataFrame:

    df = df.copy()

    df["EMA9"] = (

        df["Close"]

        .ewm(

            span=EMA_FAST,

            adjust=False,

            min_periods=EMA_FAST
        )

        .mean()
    )

    df["EMA20"] = (

        df["Close"]

        .ewm(

            span=EMA_SLOW,

            adjust=False,

            min_periods=EMA_SLOW
        )

        .mean()
    )

    df["RSI"] = calculate_rsi(
        df["Close"]
    )

    (
        df["MACD"],
        df["MACD_Signal"],
        df["MACD_Hist"]
    ) = calculate_macd(
        df["Close"]
    )

    df["ATR"] = calculate_atr(
        df
    )

    df["ATR_Pct"] = (

        df["ATR"]

        /

        df["Close"]

    ) * 100

    return df


# ====================================================================
# CANDLE FEATURES
# ====================================================================

def add_candle_features(
    df: pd.DataFrame
) -> pd.DataFrame:

    df = df.copy()

    candle_range = (

        df["High"]
        -
        df["Low"]

    ).replace(
        0,
        np.nan
    )

    body = (
        df["Close"]
        -
        df["Open"]
    )

    df["Candle_Range"] = (
        candle_range
    )

    df["Body"] = (
        body.abs()
    )

    df["Body_Pct"] = (

        body
        /
        df["Open"]

    ) * 100

    df["Candle_Strength"] = (

        df["Body"]
        /
        candle_range
    )

    df["Upper_Wick"] = (

        df["High"]

        -

        df[
            ["Open", "Close"]
        ].max(axis=1)
    )

    df["Lower_Wick"] = (

        df[
            ["Open", "Close"]
        ].min(axis=1)

        -

        df["Low"]
    )

    df["Upper_Wick_Pct"] = (

        df["Upper_Wick"]
        /
        candle_range
    )

    df["Lower_Wick_Pct"] = (

        df["Lower_Wick"]
        /
        candle_range
    )

    return df


# ====================================================================
# ALL FEATURES
# ====================================================================

def add_features(
    df: pd.DataFrame
) -> pd.DataFrame:

    df = add_historical_indicators(
        df
    )

    df = add_candle_features(
        df
    )

    df["Session_Date"] = (
        df.index.date
    )

    df["Bar_Time"] = (
        df.index.strftime(
            "%H:%M"
        )
    )

    return df


# ====================================================================
# RVOL
# ====================================================================

def calculate_rvol_for_target(
    df: pd.DataFrame,
    target_date: pd.Timestamp,
    bar_time: str,
    current_volume: float
) -> float:

    if (

        df.empty

        or current_volume <= 0
    ):

        return np.nan

    target_day = (
        target_date.date()
    )

    historical = df[

        (
            df["Session_Date"]
            <
            target_day
        )

        &

        (
            df["Bar_Time"]
            ==
            bar_time
        )

    ].copy()

    if historical.empty:

        return np.nan

    historical = (

        historical

        .sort_index()

        .tail(
            RVOL_LOOKBACK_DAYS
        )
    )

    volumes = (

        historical["Volume"]

        .replace(
            0,
            np.nan
        )

        .dropna()
    )

    if (

        len(volumes)
        <
        MIN_RVOL_OBSERVATIONS
    ):

        return np.nan

    baseline = float(
        volumes.median()
    )

    if baseline <= 0:

        return np.nan

    return (
        current_volume
        /
        baseline
    )


# ====================================================================
# NIFTY
# ====================================================================

def download_nifty_data(
    target_date: pd.Timestamp
) -> pd.DataFrame:

    start_date = (

        target_date

        -

        pd.Timedelta(
            days=WARMUP_DAYS
        )
    )

    end_date = (

        target_date

        +

        pd.Timedelta(
            days=1
        )
    )

    raw = yf_download_quiet(

        NIFTY50_TICKER,

        start=start_date.strftime(
            "%Y-%m-%d"
        ),

        end=end_date.strftime(
            "%Y-%m-%d"
        ),

        interval=SIGNAL_INTERVAL,

        auto_adjust=False,

        prepost=False,

        progress=False,

        threads=False,

        ignore_tz=False,

        timeout=DOWNLOAD_TIMEOUT,
    )

    return clean_ticker_data(
        raw
    )


def calculate_market_returns(
    nifty: pd.DataFrame,
    target_date: pd.Timestamp
) -> Tuple[float, float]:

    session = filter_session(
        nifty,
        target_date
    )

    if len(session) < 2:

        return (
            np.nan,
            np.nan
        )

    opening = session.iloc[0]

    confirmation = session.iloc[1]

    opening_return = (

        (
            float(
                opening["Close"]
            )

            -

            float(
                opening["Open"]
            )
        )

        /

        float(
            opening["Open"]
        )

    ) * 100

    total_return = (

        (
            float(
                confirmation["Close"]
            )

            -

            float(
                opening["Open"]
            )
        )

        /

        float(
            opening["Open"]
        )

    ) * 100

    return (
        opening_return,
        total_return
    )


# ====================================================================
# SCORING HELPERS
# ====================================================================

def clamp(
    value: float,
    low: float,
    high: float
) -> float:

    if not np.isfinite(value):

        return 0.0

    return float(
        np.clip(
            value,
            low,
            high
        )
    )


def bearish_move_score(
    value_pct: float,
    scale: float
) -> float:

    if not np.isfinite(
        value_pct
    ):

        return 0.0

    return clamp(

        (-value_pct / scale),

        0,

        1
    )


# ====================================================================
# EXHAUSTION
# ====================================================================

def calculate_short_exhaustion(
    opening_pct: float,
    vwap_pct: float,
    ema20_pct: float,
    rsi: float,
    lower_wick_pct: float,
    momentum_deceleration: bool
) -> Tuple[
    float,
    List[str]
]:

    penalty = 0.0

    flags: List[str] = []

    if opening_pct <= -MAX_OPENING_COLLAPSE:

        penalty += 12

        flags.append(
            "opening collapse"
        )

    elif opening_pct <= -2.25:

        penalty += 6

        flags.append(
            "large opening move"
        )

    if vwap_pct <= -MAX_SHORT_VWAP_DISTANCE:

        penalty += 12

        flags.append(
            "far below VWAP"
        )

    elif vwap_pct <= -2.0:

        penalty += 6

        flags.append(
            "extended VWAP"
        )

    if ema20_pct <= -MAX_SHORT_EMA20_DISTANCE:

        penalty += 10

        flags.append(
            "far below EMA20"
        )

    elif ema20_pct <= -2.5:

        penalty += 5

        flags.append(
            "extended EMA20"
        )

    if np.isfinite(rsi):

        if rsi <= RSI_EXTREME_OVERSOLD:

            penalty += 15

            flags.append(
                "extreme oversold"
            )

        elif rsi <= RSI_OVERSOLD:

            penalty += 8

            flags.append(
                "oversold"
            )

    if np.isfinite(
        lower_wick_pct
    ):

        if lower_wick_pct >= 0.45:

            penalty += 8

            flags.append(
                "large lower wick"
            )

        elif lower_wick_pct >= 0.30:

            penalty += 4

            flags.append(
                "lower wick"
            )

    if momentum_deceleration:

        penalty += 8

        flags.append(
            "momentum deceleration"
        )

    return (
        penalty,
        flags
    )


# ====================================================================
# ANALYSE 09:45
# ====================================================================

def analyse_at_0945(
    ticker: str,
    full_df: pd.DataFrame,
    target_date: pd.Timestamp,
    nifty_opening_return: float,
    nifty_total_return: float
) -> Optional[dict]:

    if full_df.empty:

        return None

    df = add_features(
        full_df
    )

    session = filter_session(
        df,
        target_date
    )

    # We need both 09:15 and 09:30 bars.
    if len(session) < 2:

        return None

    opening = session.iloc[0]

    confirmation = session.iloc[1]

    opening_price = float(
        opening["Open"]
    )

    opening_close = float(
        opening["Close"]
    )

    confirmation_open = float(
        confirmation["Open"]
    )

    decision_price = float(
        confirmation["Close"]
    )

    # ============================================================
    # MOVEMENT
    # ============================================================

    opening_pct = (

        (
            opening_close
            -
            opening_price
        )

        /

        opening_price

    ) * 100

    confirmation_pct = (

        (
            decision_price
            -
            confirmation_open
        )

        /

        confirmation_open

    ) * 100

    total_pct = (

        (
            decision_price
            -
            opening_price
        )

        /

        opening_price

    ) * 100

    # ============================================================
    # RELATIVE STRENGTH
    # ============================================================

    relative_opening_strength = (

        opening_pct
        -
        nifty_opening_return

        if np.isfinite(
            nifty_opening_return
        )

        else np.nan
    )

    relative_total_strength = (

        total_pct
        -
        nifty_total_return

        if np.isfinite(
            nifty_total_return
        )

        else np.nan
    )

    # ============================================================
    # INDICATORS
    # ============================================================

    vwap = calculate_session_vwap(
        session
    )

    vwap_value = float(
        vwap.iloc[1]
    )

    ema9 = float(
        confirmation["EMA9"]
    )

    ema20 = float(
        confirmation["EMA20"]
    )

    rsi = (

        float(
            confirmation["RSI"]
        )

        if pd.notna(
            confirmation["RSI"]
        )

        else np.nan
    )

    macd = (

        float(
            confirmation["MACD"]
        )

        if pd.notna(
            confirmation["MACD"]
        )

        else np.nan
    )

    macd_signal = (

        float(
            confirmation["MACD_Signal"]
        )

        if pd.notna(
            confirmation["MACD_Signal"]
        )

        else np.nan
    )

    macd_hist = (

        float(
            confirmation["MACD_Hist"]
        )

        if pd.notna(
            confirmation["MACD_Hist"]
        )

        else np.nan
    )

    atr = (

        float(
            confirmation["ATR"]
        )

        if pd.notna(
            confirmation["ATR"]
        )

        else np.nan
    )

    atr_pct = (

        float(
            confirmation["ATR_Pct"]
        )

        if pd.notna(
            confirmation["ATR_Pct"]
        )

        else np.nan
    )

    # ============================================================
    # PRICE LOCATION
    # ============================================================

    vwap_pct = (

        (
            decision_price
            -
            vwap_value
        )

        /

        vwap_value

    ) * 100

    ema20_pct = (

        (
            decision_price
            -
            ema20
        )

        /

        ema20

    ) * 100

    ema9_pct = (

        (
            decision_price
            -
            ema9
        )

        /

        ema9

    ) * 100

    ema_spread_pct = (

        (
            ema9
            -
            ema20
        )

        /

        ema20

    ) * 100

    # ============================================================
    # ATR
    # ============================================================

    if (

        np.isfinite(atr)

        and atr > 0
    ):

        normalized_total_move = (

            (
                decision_price
                -
                opening_price
            )

            /

            atr
        )

    else:

        normalized_total_move = np.nan

    # ============================================================
    # STRUCTURE
    # ============================================================

    opening_high = float(
        opening["High"]
    )

    opening_low = float(
        opening["Low"]
    )

    confirmation_high = float(
        confirmation["High"]
    )

    confirmation_low = float(
        confirmation["Low"]
    )

    lower_low = (
        confirmation_low
        <
        opening_low
    )

    confirmation_range = float(
        confirmation["Candle_Range"]
    )

    opening_range = (
        opening_high
        -
        opening_low
    )

    range_expansion = (

        confirmation_range
        /
        opening_range

        if opening_range > 0

        else np.nan
    )

    bearish_confirmation = (
        decision_price
        <
        confirmation_open
    )

    lower_wick_pct = (

        float(
            confirmation[
                "Lower_Wick_Pct"
            ]
        )

        if pd.notna(
            confirmation[
                "Lower_Wick_Pct"
            ]
        )

        else np.nan
    )

    upper_wick_pct = (

        float(
            confirmation[
                "Upper_Wick_Pct"
            ]
        )

        if pd.notna(
            confirmation[
                "Upper_Wick_Pct"
            ]
        )

        else np.nan
    )

    candle_strength = (

        float(
            confirmation[
                "Candle_Strength"
            ]
        )

        if pd.notna(
            confirmation[
                "Candle_Strength"
            ]
        )

        else np.nan
    )

    # ============================================================
    # RVOL
    # ============================================================

    opening_rvol = (
        calculate_rvol_for_target(

            df,

            target_date,

            "09:15",

            float(
                opening["Volume"]
            )
        )
    )

    confirmation_rvol = (
        calculate_rvol_for_target(

            df,

            target_date,

            "09:30",

            float(
                confirmation["Volume"]
            )
        )
    )

    # ============================================================
    # MOMENTUM
    # ============================================================

    momentum_deceleration = (

        opening_pct < -0.75

        and

        confirmation_pct
        >
        opening_pct * 0.55

        and

        confirmation_pct > -0.25
    )

    momentum_acceleration = (

        opening_pct < 0

        and

        confirmation_pct
        <
        opening_pct * 0.75
    )

    short_continuation = (

        opening_pct < -0.25

        and

        confirmation_pct < -0.10

        and

        lower_low
    )

    short_reversal = (

        opening_pct < -0.75

        and

        confirmation_pct > 0.30

        and

        not lower_low
    )

    # ============================================================
    # EXHAUSTION
    # ============================================================

    exhaustion_penalty, exhaustion_flags = (

        calculate_short_exhaustion(

            opening_pct,

            vwap_pct,

            ema20_pct,

            rsi,

            lower_wick_pct,

            momentum_deceleration
        )
    )

    # ============================================================
    # SHORT SCORE
    # ============================================================

    short_score = 0.0

    # Opening momentum
    short_score += (

        12

        *

        bearish_move_score(
            opening_pct,
            1.50
        )
    )

    # Confirmation momentum
    short_score += (

        12

        *

        bearish_move_score(
            confirmation_pct,
            1.00
        )
    )

    # Relative weakness
    short_score += (

        12

        *

        bearish_move_score(
            relative_total_strength,
            1.50
        )
    )

    # VWAP
    short_score += (

        10

        *

        clamp(
            -vwap_pct / 2.0,
            0,
            1
        )
    )

    # EMA structure
    ema_structure = 0.0

    if decision_price < ema20:

        ema_structure += 0.50

    if ema9 < ema20:

        ema_structure += 0.50

    short_score += (
        10
        *
        ema_structure
    )

    # MACD
    macd_structure = 0.0

    if (

        np.isfinite(macd)

        and

        np.isfinite(macd_signal)

        and

        macd < macd_signal
    ):

        macd_structure += 0.60

    if (

        np.isfinite(macd_hist)

        and

        macd_hist < 0
    ):

        macd_structure += 0.40

    short_score += (

        8

        *

        min(
            1.0,
            macd_structure
        )
    )

    # Volume
    volume_strength = 0.0

    if np.isfinite(
        opening_rvol
    ):

        volume_strength += (

            clamp(

                (
                    opening_rvol
                    -
                    1.0
                )
                /
                1.5,

                0,

                1

            )

            *

            0.40
        )

    if np.isfinite(
        confirmation_rvol
    ):

        volume_strength += (

            clamp(

                (
                    confirmation_rvol
                    -
                    1.0
                )
                /
                1.5,

                0,

                1

            )

            *

            0.60
        )

    short_score += (

        8

        *

        min(
            1.0,
            volume_strength
        )
    )

    # Structure
    structure_score = 0.0

    if lower_low:

        structure_score += 0.60

    if bearish_confirmation:

        structure_score += 0.20

    if (

        np.isfinite(
            lower_wick_pct
        )

        and

        lower_wick_pct < 0.20
    ):

        structure_score += 0.20

    short_score += (

        10

        *

        min(
            1.0,
            structure_score
        )
    )

    # Range expansion
    if np.isfinite(
        range_expansion
    ):

        short_score += (

            5

            *

            clamp(

                (
                    range_expansion
                    -
                    0.75
                )
                /
                0.75,

                0,

                1
            )
        )

    # ATR normalization
    if np.isfinite(
        normalized_total_move
    ):

        short_score += (

            5

            *

            clamp(

                -normalized_total_move
                /
                2.0,

                0,

                1
            )
        )

    # Continuation
    if short_continuation:

        short_score += 6

    # Acceleration
    if momentum_acceleration:

        short_score += 4

    # Reversal
    if short_reversal:

        short_score -= 25

    # Exhaustion
    short_score -= exhaustion_penalty

    # RSI balance
    if np.isfinite(rsi):

        if 32 <= rsi <= 55:

            short_score += 5

        elif 28 <= rsi < 32:

            short_score += 2

        elif rsi < 22:

            short_score -= 5

    short_score = clamp(
        short_score,
        0,
        100
    )

    # ============================================================
    # LIQUIDITY
    # ============================================================

    turnover_cr = (

        float(
            confirmation["Volume"]
        )

        *

        decision_price

        /

        10_000_000
    )

    # ============================================================
    # SIGNAL
    # ============================================================

    signal = "AVOID"

    conviction = "NEUTRAL"

    if (

        short_score
        >=
        SHORT_TRADEABLE_SCORE

        and

        total_pct
        <=
        -MIN_SHORT_TOTAL_MOVE

        and

        opening_pct
        <=
        -MIN_OPENING_SHORT_MOVE

        and

        not short_reversal
    ):

        signal = "SHORT"

        if (

            short_score
            >=
            SHORT_HIGH_CONVICTION_SCORE
        ):

            conviction = "HIGH"

        else:

            conviction = "TRADEABLE"

    indicator_ready = all(

        np.isfinite(value)

        for value in [

            ema9,

            ema20,

            rsi,

            atr,
        ]
    )

    if not indicator_ready:

        return None

    return {

        "Ticker":
            ticker.replace(
                ".NS",
                ""
            ),

        "Signal":
            signal,

        "Conviction":
            conviction,

        "Score":
            round(
                short_score,
                2
            ),

        "Opening %":
            opening_pct,

        "09:30-09:45 %":
            confirmation_pct,

        "Total %":
            total_pct,

        "NIFTY Opening %":
            nifty_opening_return,

        "NIFTY Total %":
            nifty_total_return,

        "Relative Total %":
            relative_total_strength,

        "Price":
            decision_price,

        "VWAP %":
            vwap_pct,

        "EMA20 %":
            ema20_pct,

        "EMA9 %":
            ema9_pct,

        "EMA Spread %":
            ema_spread_pct,

        "ATR %":
            atr_pct,

        "ATR Move":
            normalized_total_move,

        "Opening RVOL":
            opening_rvol,

        "Confirmation RVOL":
            confirmation_rvol,

        "RSI":
            rsi,

        "MACD Hist":
            macd_hist,

        "Turnover Cr":
            turnover_cr,

        "Lower Low":
            lower_low,

        "Range Expansion":
            range_expansion,

        "Candle Strength":
            candle_strength,

        "Lower Wick":
            lower_wick_pct,

        "Exhaustion Penalty":
            exhaustion_penalty,

        "Exhaustion Flags":
            ", ".join(
                exhaustion_flags
            )
            if exhaustion_flags
            else "",

        "Decision Timestamp":
            confirmation.name,
    }


# ====================================================================
# MARKET-DAY VALIDATION
# ====================================================================

def has_required_bars(
    nifty: pd.DataFrame,
    target_date: pd.Timestamp
) -> bool:

    session = filter_session(
        nifty,
        target_date
    )

    return len(session) >= 2


# ====================================================================
# SCAN
# ====================================================================

def scan_live(
    target_date: pd.Timestamp
) -> Tuple[
    pd.DataFrame,
    dict
]:

    tickers = build_universe()

    # ================================================================
    # NIFTY
    # ================================================================

    print(
        "Downloading NIFTY 50 benchmark..."
    )

    nifty = download_nifty_data(
        target_date
    )

    (
        nifty_opening_return,
        nifty_total_return
    ) = calculate_market_returns(
        nifty,
        target_date
    )

    if not has_required_bars(
        nifty,
        target_date
    ):

        print()
        print(
            "09:45 benchmark candles "
            "are not available."
        )

        return (
            pd.DataFrame(),
            {
                "status":
                    "NO_0945_DATA",

                "nifty_opening":
                    np.nan,

                "nifty_total":
                    np.nan,

                "universe":
                    len(tickers),

                "downloaded":
                    0,

                "signals":
                    0,
            }
        )

    print(
        f"NIFTY 50 09:45 return: "
        f"{nifty_total_return:+.2f}%"
    )

    # ================================================================
    # STOCK SCAN
    # ================================================================

    all_results: List[dict] = []

    total = len(tickers)

    processed = 0

    downloaded_count = 0

    for start_idx in range(
        0,
        total,
        BATCH_SIZE
    ):

        batch = tickers[

            start_idx:
            start_idx + BATCH_SIZE
        ]

        batch_data = (
            download_intraday_batch(

                batch,

                target_date
            )
        )

        downloaded_count += len(
            batch_data
        )

        for ticker in batch:

            processed += 1

            progress_line(

                f"Scanning "
                f"{processed}/{total} | "
                f"Signals: "
                f"{len(all_results)}"
            )

            try:

                raw_df = batch_data.get(
                    ticker
                )

                if raw_df is None:

                    continue

                analysis = (
                    analyse_at_0945(

                        ticker,

                        raw_df,

                        target_date,

                        nifty_opening_return,

                        nifty_total_return,
                    )
                )

                if analysis is None:

                    continue

                # Liquidity
                if (

                    analysis[
                        "Turnover Cr"
                    ]

                    <

                    MIN_TURNOVER_CR
                ):

                    continue

                # Only actionable short signals.
                if (

                    analysis[
                        "Signal"
                    ]

                    !=

                    "SHORT"
                ):

                    continue

                all_results.append(
                    analysis
                )

            except Exception as exc:

                # Do not kill the complete scan
                # because of one ticker.
                print(
                    f"\nTicker error "
                    f"{ticker}: {exc}"
                )

        time.sleep(
            BATCH_DELAY
        )

    clear_line()

    if not all_results:

        results = pd.DataFrame()

    else:

        results = pd.DataFrame(
            all_results
        )

        results = results.sort_values(

            "Score",

            ascending=False
        ).reset_index(
            drop=True
        )

    stats = {

        "status":
            "OK",

        "nifty_opening":
            nifty_opening_return,

        "nifty_total":
            nifty_total_return,

        "universe":
            total,

        "downloaded":
            downloaded_count,

        "signals":
            len(results),
    }

    return (
        results,
        stats
    )


# ====================================================================
# TELEGRAM FORMATTING
# ====================================================================

def safe_float(
    value
) -> Optional[float]:

    try:

        value = float(value)

        if np.isfinite(value):

            return value

    except Exception:

        pass

    return None


def fmt_pct(
    value
) -> str:

    value = safe_float(
        value
    )

    if value is None:

        return "-"

    return f"{value:+.2f}%"


def fmt_rvol(
    value
) -> str:

    value = safe_float(
        value
    )

    if value is None:

        return "-"

    return f"{value:.2f}x"


def fmt_score(
    value
) -> str:

    value = safe_float(
        value
    )

    if value is None:

        return "-"

    return f"{value:.0f}"


def fmt_price(
    value
) -> str:

    value = safe_float(
        value
    )

    if value is None:

        return "-"

    return f"₹{value:,.2f}"


def build_telegram_message(
    target_date: pd.Timestamp,
    results: pd.DataFrame,
    stats: dict
) -> str:

    now = get_current_ist()

    nifty_total = stats[
        "nifty_total"
    ]

    universe = stats[
        "universe"
    ]

    downloaded = stats[
        "downloaded"
    ]

    signals = stats[
        "signals"
    ]

    lines: List[str] = []

    lines.append(
        "🔴 <b>NSE 09:45 SHORT SCANNER</b>"
    )

    lines.append("")

    lines.append(
        f"📅 {target_date:%d-%b-%Y}"
    )

    lines.append(
        f"⏱ {now:%H:%M:%S} IST"
    )

    lines.append(
        f"📊 NIFTY 50: "
        f"<b>{fmt_pct(nifty_total)}</b>"
    )

    lines.append("")

    lines.append(
        f"Universe: {universe}"
    )

    lines.append(
        f"Data received: {downloaded}"
    )

    lines.append(
        f"Short signals: {signals}"
    )

    lines.append("")

    if results.empty:

        lines.append(
            "🟡 <b>No qualifying short setups.</b>"
        )

    else:

        lines.append(
            "🔥 <b>TOP SHORT CANDIDATES</b>"
        )

        lines.append("")

        for rank, (
            _,
            row
        ) in enumerate(

            results.head(
                TOP_SHORTS_TO_SEND
            ).iterrows(),

            start=1
        ):

            ticker = row[
                "Ticker"
            ]

            score = row[
                "Score"
            ]

            conviction = row[
                "Conviction"
            ]

            lines.append(

                f"<b>{rank}. {ticker}</b> "
                f"— Score <b>{fmt_score(score)}</b>"
            )

            lines.append(

                f"   {conviction} | "
                f"Price {fmt_price(row['Price'])}"
            )

            lines.append(

                f"   Open {fmt_pct(row['Opening %'])} | "
                f"09:30–09:45 "
                f"{fmt_pct(row['09:30-09:45 %'])}"
            )

            lines.append(

                f"   Total {fmt_pct(row['Total %'])} | "
                f"Relative {fmt_pct(row['Relative Total %'])}"
            )

            lines.append(

                f"   VWAP {fmt_pct(row['VWAP %'])} | "
                f"EMA20 {fmt_pct(row['EMA20 %'])}"
            )

            lines.append(

                f"   RVOL "
                f"{fmt_rvol(row['Confirmation RVOL'])} | "
                f"RSI {safe_float(row['RSI']):.1f}"
                if safe_float(row["RSI"]) is not None
                else
                f"   RVOL "
                f"{fmt_rvol(row['Confirmation RVOL'])} | "
                f"RSI -"
            )

            flags = row[
                "Exhaustion Flags"
            ]

            if flags:

                lines.append(

                    f"   ⚠️ Exhaustion: "
                    f"{flags}"
                )

            lines.append("")

    if downloaded < universe:

        lines.append(
            "⚠️ <b>DATA WARNING:</b> "
            f"{universe - downloaded} "
            "symbols were not downloaded."
        )

        lines.append("")

    lines.append(
        "⚠️ <i>Research scanner only. "
        "Not a trading recommendation.</i>"
    )

    return "\n".join(
        lines
    )


# ====================================================================
# LOCAL CONSOLE OUTPUT
# ====================================================================

def print_console_results(
    results: pd.DataFrame,
    stats: dict
) -> None:

    print()

    print(
        "=" * 100
    )

    print(
        "NSE 09:45 LIVE SHORT SCANNER"
    )

    print(
        "=" * 100
    )

    print(
        f"NIFTY 50: "
        f"{fmt_pct(stats['nifty_total'])}"
    )

    print(
        f"Universe: "
        f"{stats['universe']}"
    )

    print(
        f"Downloaded: "
        f"{stats['downloaded']}"
    )

    print(
        f"Signals: "
        f"{stats['signals']}"
    )

    print(
        "=" * 100
    )

    if results.empty:

        print(
            "No qualifying short signals."
        )

        return

    display = results.head(
        TOP_SHORTS_TO_SEND
    ).copy()

    columns = [

        "Ticker",

        "Conviction",

        "Score",

        "Opening %",

        "09:30-09:45 %",

        "Total %",

        "Relative Total %",

        "Price",

        "VWAP %",

        "EMA20 %",

        "Opening RVOL",

        "Confirmation RVOL",

        "RSI",

        "Turnover Cr",
    ]

    display = display[
        columns
    ]

    print(
        display.to_string(
            index=False
        )
    )


# ====================================================================
# CSV EXPORT
# ====================================================================

def export_results(
    results: pd.DataFrame
) -> None:

    if not EXPORT_RESULTS:

        return

    try:

        if results.empty:

            return

        results.to_csv(

            EXPORT_FILENAME,

            index=False
        )

        print(
            f"Results exported: "
            f"{EXPORT_FILENAME}"
        )

    except Exception as exc:

        print(
            f"CSV export failed: "
            f"{exc}"
        )


# ====================================================================
# MARKET TIME CHECK
# ====================================================================

def check_execution_time() -> None:

    now = get_current_ist()

    decision = datetime_from_time(
        DECISION_TIME
    )

    if now.time() < decision:

        print()

        print(
            "WARNING:"
        )

        print(
            "09:45 candle is not complete."
        )

        print(
            f"Current IST time: "
            f"{now:%H:%M:%S}"
        )

        print(
            "The scanner should normally "
            "run after 09:45 IST."
        )

        print()


def datetime_from_time(
    value: str
):

    return pd.Timestamp(
        value
    ).time()


# ====================================================================
# MAIN
# ====================================================================

def main() -> int:

    start_time = time.perf_counter()

    print()
    print(
        "=" * 100
    )

    print(
        "NSE 09:45 LIVE TELEGRAM SCANNER"
    )

    print(
        "=" * 100
    )

    now = get_current_ist()

    target_date = get_target_date()

    print(
        f"Current IST: "
        f"{now:%Y-%m-%d %H:%M:%S}"
    )

    print(
        f"Target date: "
        f"{target_date:%Y-%m-%d}"
    )

    # ------------------------------------------------------------
    # Time check
    # ------------------------------------------------------------

    check_execution_time()

    # ------------------------------------------------------------
    # Telegram configuration
    # ------------------------------------------------------------

    if telegram_enabled():

        print(
            "Telegram: ENABLED"
        )

    else:

        print(
            "Telegram: DISABLED"
        )

        print(
            "Set TELEGRAM_BOT_TOKEN and "
            "TELEGRAM_CHAT_ID."
        )

    # ------------------------------------------------------------
    # Scan
    # ------------------------------------------------------------

    try:

        results, stats = scan_live(
            target_date
        )

    except Exception as exc:

        print()

        print(
            "FATAL SCANNER ERROR:"
        )

        print(exc)

        error_message = (

            "🚨 <b>NSE SCANNER ERROR</b>\n\n"

            f"Date: {target_date:%d-%b-%Y}\n"

            f"Time: {now:%H:%M:%S} IST\n\n"

            f"<b>Error:</b>\n"
            f"{str(exc)[:3000]}"
        )

        send_telegram_message(
            error_message
        )

        return 1

    # ------------------------------------------------------------
    # Output
    # ------------------------------------------------------------

    print_console_results(
        results,
        stats
    )

    export_results(
        results
    )

    # ------------------------------------------------------------
    # Telegram
    # ------------------------------------------------------------

    message = build_telegram_message(

        target_date,

        results,

        stats
    )

    print()

    print(
        "Sending Telegram notification..."
    )

    send_telegram_message(
        message
    )

    # ------------------------------------------------------------
    # Runtime
    # ------------------------------------------------------------

    elapsed = (
        time.perf_counter()
        -
        start_time
    )

    print()

    print(
        "=" * 100
    )

    print(
        f"Runtime: {elapsed:.1f} seconds"
    )

    print(
        "Scanner completed."
    )

    print(
        "=" * 100
    )

    return 0


# ====================================================================
# ENTRY POINT
# ====================================================================

if __name__ == "__main__":

    sys.exit(
        main()
    )
