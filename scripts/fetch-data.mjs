/**
 * Bitcoin Re-Entry Signal — Data Fetcher & Indicator Engine
 *
 * Pulls from free APIs:
 *   - CoinGecko (price, market cap, volume history)
 *   - Alternative.me (Fear & Greed Index)
 *   - Binance (perpetual funding rates)
 *   - Blockchain.com (hash rate, difficulty)
 *
 * Computes all indicators and saves to data/indicators.json
 */

import { writeFileSync, mkdirSync, existsSync, readFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const DATA_DIR = join(__dirname, '..', 'data');

// --- Helpers ---

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function fetchJSON(url, label) {
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    console.log(`  ✓ ${label}`);
    return data;
  } catch (e) {
    console.log(`  ✗ ${label}: ${e.message}`);
    return null;
  }
}

// --- Moving Average helpers ---

function sma(arr, period) {
  if (arr.length < period) return null;
  const slice = arr.slice(-period);
  return slice.reduce((a, b) => a + b, 0) / period;
}

function ema(arr, period) {
  if (arr.length < period) return null;
  const k = 2 / (period + 1);
  let emaVal = sma(arr.slice(0, period), period);
  for (let i = period; i < arr.length; i++) {
    emaVal = arr[i] * k + emaVal * (1 - k);
  }
  return emaVal;
}

// Standard deviation
function stddev(arr) {
  const mean = arr.reduce((a, b) => a + b, 0) / arr.length;
  const variance = arr.reduce((a, b) => a + (b - mean) ** 2, 0) / arr.length;
  return Math.sqrt(variance);
}

// --- Data Fetching ---

async function fetchPriceHistory() {
  // CoinGecko: max days for free = 365 without key, but /market_chart with vs_currency works for longer ranges
  // We'll fetch max range (free tier allows "max" parameter)
  console.log('\n📊 Fetching BTC price history...');

  // Fetch full history (CoinGecko "max" gives daily data for full history)
  const data = await fetchJSON(
    'https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=max&interval=daily',
    'CoinGecko full price history'
  );

  if (!data) return null;

  return {
    prices: data.prices.map(([ts, price]) => ({ ts, date: new Date(ts).toISOString().split('T')[0], price })),
    marketCaps: data.market_caps.map(([ts, cap]) => ({ ts, cap })),
    volumes: data.total_volumes.map(([ts, vol]) => ({ ts, vol }))
  };
}

async function fetchFearGreed() {
  console.log('\n😱 Fetching Fear & Greed Index...');
  const data = await fetchJSON(
    'https://api.alternative.me/fng/?limit=365&format=json',
    'Alternative.me Fear & Greed (365 days)'
  );
  if (!data?.data) return null;
  return data.data.map(d => ({
    ts: parseInt(d.timestamp) * 1000,
    date: new Date(parseInt(d.timestamp) * 1000).toISOString().split('T')[0],
    value: parseInt(d.value),
    label: d.value_classification
  }));
}

async function fetchFundingRates() {
  console.log('\n💰 Fetching Binance funding rates...');
  const data = await fetchJSON(
    'https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=100',
    'Binance BTCUSDT funding rates (last 100)'
  );
  if (!data) return null;
  return data.map(d => ({
    ts: d.fundingTime,
    date: new Date(d.fundingTime).toISOString().split('T')[0],
    rate: parseFloat(d.fundingRate)
  }));
}

async function fetchHashRate() {
  console.log('\n⛏️  Fetching hash rate data...');
  // Blockchain.com API for hash rate (TH/s, daily)
  const data = await fetchJSON(
    'https://api.blockchain.info/charts/hash-rate?timespan=2years&format=json&rollingAverage=1days',
    'Blockchain.com hash rate (2 years)'
  );
  if (!data?.values) return null;
  return data.values.map(d => ({
    ts: d.x * 1000,
    date: new Date(d.x * 1000).toISOString().split('T')[0],
    hashRate: d.y // TH/s
  }));
}

async function fetchDifficulty() {
  console.log('\n🔧 Fetching difficulty data...');
  const data = await fetchJSON(
    'https://api.blockchain.info/charts/difficulty?timespan=2years&format=json',
    'Blockchain.com difficulty (2 years)'
  );
  if (!data?.values) return null;
  return data.values.map(d => ({
    ts: d.x * 1000,
    date: new Date(d.x * 1000).toISOString().split('T')[0],
    difficulty: d.y
  }));
}

async function fetchMinerRevenue() {
  console.log('\n💵 Fetching miner revenue data...');
  const data = await fetchJSON(
    'https://api.blockchain.info/charts/miners-revenue?timespan=2years&format=json&rollingAverage=1days',
    'Blockchain.com miner revenue (2 years)'
  );
  if (!data?.values) return null;
  return data.values.map(d => ({
    ts: d.x * 1000,
    date: new Date(d.x * 1000).toISOString().split('T')[0],
    revenue: d.y // USD
  }));
}

// --- Indicator Computation ---

function computeIndicators(priceHistory, fearGreed, fundingRates, hashRate, minerRevenue) {
  const prices = priceHistory.prices;
  const dailyPrices = prices.map(p => p.price);
  const currentPrice = dailyPrices[dailyPrices.length - 1];
  const currentDate = prices[prices.length - 1].date;

  console.log(`\n🔢 Computing indicators (current price: $${currentPrice.toLocaleString()}, date: ${currentDate})...`);

  const indicators = {};

  // ============================
  // DOMAIN 1: ON-CHAIN VALUATION
  // ============================

  // 1.1 Mayer Multiple (price / 200d SMA)
  const sma200d = sma(dailyPrices, 200);
  const mayerMultiple = sma200d ? currentPrice / sma200d : null;
  indicators.mayerMultiple = {
    name: 'Mayer Multiple',
    value: mayerMultiple ? +mayerMultiple.toFixed(4) : null,
    sma200d: sma200d ? +sma200d.toFixed(2) : null,
    thresholds: { deepBottom: 0.6, bottom: 0.8, neutral: 1.0, overbought: 2.4 },
    description: 'Price / 200-day MA. Below 0.8 = oversold, below 0.6 = deep capitulation'
  };

  // 1.2 MVRV-Z Score (estimated from market cap data)
  // We can approximate using market cap vs a simple "realized cap" proxy
  // True realized cap needs UTXO data, but we can use a rough proxy
  const marketCaps = priceHistory.marketCaps.map(m => m.cap);
  const currentMarketCap = marketCaps[marketCaps.length - 1];

  // Proxy for realized cap: 200-day MA of market cap (rough approximation)
  const realizedCapProxy = sma(marketCaps, 200);
  const mvrvProxy = realizedCapProxy ? currentMarketCap / realizedCapProxy : null;
  const mvrvZProxy = realizedCapProxy ? (currentMarketCap - realizedCapProxy) / stddev(marketCaps.slice(-365)) : null;

  indicators.mvrvZScore = {
    name: 'MVRV-Z Score (Estimated)',
    value: mvrvZProxy ? +mvrvZProxy.toFixed(2) : null,
    mvrvRatio: mvrvProxy ? +mvrvProxy.toFixed(4) : null,
    note: 'Estimated from market cap data. Check Glassnode/Bitcoin Magazine Pro for exact values',
    thresholds: { deepBottom: -1.0, bottom: 0, neutral: 2.0, danger: 4.0, extreme: 7.0 },
    description: 'Deviation of market cap from realized cap. Below 0 = undervalued'
  };

  // 1.3 200-Week Moving Average
  // Convert daily prices to weekly (every 7th price)
  const weeklyPrices = [];
  for (let i = 0; i < dailyPrices.length; i += 7) {
    weeklyPrices.push(dailyPrices[i]);
  }
  const wma200 = sma(weeklyPrices, 200);
  const wma200Ratio = wma200 ? currentPrice / wma200 : null;

  indicators.wma200 = {
    name: '200-Week MA',
    value: wma200 ? +wma200.toFixed(2) : null,
    ratio: wma200Ratio ? +wma200Ratio.toFixed(4) : null,
    currentPrice: +currentPrice.toFixed(2),
    percentAbove: wma200Ratio ? +((wma200Ratio - 1) * 100).toFixed(1) : null,
    thresholds: { atOrBelow: 1.0, close: 1.2, neutral: 1.5 },
    description: 'Historic cycle floor. Price at or below 200WMA = major buy zone'
  };

  // 1.4 Rainbow Chart (Logarithmic regression bands)
  // Rainbow uses log regression: y = a * ln(x) + b, where x = days since Jan 9, 2009
  const genesisDate = new Date('2009-01-09').getTime();
  const daysSinceGenesis = (Date.now() - genesisDate) / (1000 * 60 * 60 * 24);

  // Approximate rainbow regression coefficients (fitted to historical data)
  const logDays = Math.log(daysSinceGenesis);
  const rainbowCenter = Math.exp(-17.01593313 + 5.11364342 * logDays);

  // Rainbow bands are offsets from center (approximately)
  const rainbowBands = {
    'Fire Sale': rainbowCenter * 0.35,
    'BUY!': rainbowCenter * 0.55,
    'Accumulate': rainbowCenter * 0.85,
    'Still Cheap': rainbowCenter * 1.15,
    'HODL!': rainbowCenter * 1.55,
    'Is this a bubble?': rainbowCenter * 2.1,
    'FOMO intensifies': rainbowCenter * 2.85,
    'Sell. Seriously, SELL!': rainbowCenter * 3.85,
    'Maximum Bubble': rainbowCenter * 5.2
  };

  // Find current band
  let currentBand = 'Maximum Bubble';
  const bandNames = Object.keys(rainbowBands);
  for (let i = 0; i < bandNames.length - 1; i++) {
    if (currentPrice <= rainbowBands[bandNames[i + 1]]) {
      currentBand = bandNames[i];
      break;
    }
  }

  indicators.rainbowChart = {
    name: 'Rainbow Chart',
    currentBand,
    bands: Object.fromEntries(Object.entries(rainbowBands).map(([k, v]) => [k, +v.toFixed(0)])),
    description: 'Logarithmic regression bands. Lower bands = deeper value'
  };

  // 1.5 Power Law Model
  // Price = exp(5.71 * ln(days) - 38.16)
  const powerLawFair = Math.exp(5.71 * Math.log(daysSinceGenesis) - 38.16);
  const powerLawRatio = currentPrice / powerLawFair;

  // Power law support (lower bound, ~40% of fair value historically)
  const powerLawSupport = powerLawFair * 0.4;

  indicators.powerLaw = {
    name: 'Power Law Model',
    fairValue: +powerLawFair.toFixed(0),
    support: +powerLawSupport.toFixed(0),
    currentRatio: +powerLawRatio.toFixed(4),
    description: 'Long-term power function trend. Ratio < 0.5 = near support, > 2.0 = overextended'
  };

  // ============================
  // DOMAIN 2: MINER HEALTH
  // ============================

  // 2.1 Hash Ribbon (30d MA vs 60d MA of hash rate)
  let hashRibbonSignal = null;
  let hr30dMA = null;
  let hr60dMA = null;

  if (hashRate && hashRate.length >= 60) {
    const hrValues = hashRate.map(h => h.hashRate);
    hr30dMA = sma(hrValues, 30);
    hr60dMA = sma(hrValues, 60);

    if (hr30dMA && hr60dMA) {
      if (hr30dMA < hr60dMA) {
        hashRibbonSignal = 'CAPITULATION';
      } else {
        // Check if recently crossed (within last 30 days)
        const prev30 = sma(hrValues.slice(0, -1), 30);
        const prev60 = sma(hrValues.slice(0, -1), 60);
        if (prev30 && prev60 && prev30 < prev60) {
          hashRibbonSignal = 'BUY_SIGNAL';
        } else {
          hashRibbonSignal = 'RECOVERY';
        }
      }
    }
  }

  indicators.hashRibbon = {
    name: 'Hash Ribbon',
    signal: hashRibbonSignal,
    ma30d: hr30dMA ? +hr30dMA.toFixed(2) : null,
    ma60d: hr60dMA ? +hr60dMA.toFixed(2) : null,
    description: 'Miner capitulation/recovery. Buy signal fires when 30d MA crosses above 60d MA after capitulation'
  };

  // 2.2 Puell Multiple (daily miner revenue / 365d MA of miner revenue)
  let puellMultiple = null;
  if (minerRevenue && minerRevenue.length >= 365) {
    const revenues = minerRevenue.map(m => m.revenue);
    const currentRevenue = revenues[revenues.length - 1];
    const avgRevenue365 = sma(revenues, 365);
    if (avgRevenue365 && avgRevenue365 > 0) {
      puellMultiple = currentRevenue / avgRevenue365;
    }
  }

  indicators.puellMultiple = {
    name: 'Puell Multiple',
    value: puellMultiple ? +puellMultiple.toFixed(4) : null,
    thresholds: { deepGreen: 0.3, green: 0.5, neutral: 1.0, red: 3.0, deepRed: 4.5 },
    description: 'Miner revenue vs 365d avg. Below 0.5 = miner capitulation / accumulation zone'
  };

  // ============================
  // DOMAIN 3: TECHNICAL / PRICE
  // ============================

  // 3.1 Pi Cycle Bottom (150d EMA vs 471d SMA × 0.475)
  const ema150 = ema(dailyPrices, 150);
  const sma471 = sma(dailyPrices, 471);
  const piCycleBottomLine = sma471 ? sma471 * 0.475 : null;
  let piCycleBottomSignal = null;

  if (ema150 && piCycleBottomLine) {
    piCycleBottomSignal = ema150 < piCycleBottomLine ? 'BOTTOM_ZONE' : 'ABOVE';
  }

  indicators.piCycleBottom = {
    name: 'Pi Cycle Bottom',
    signal: piCycleBottomSignal,
    ema150: ema150 ? +ema150.toFixed(2) : null,
    sma471x0475: piCycleBottomLine ? +piCycleBottomLine.toFixed(2) : null,
    description: '150d EMA crossing below 471d SMA × 0.475 signals cycle bottom'
  };

  // 3.2 Cycle Timing
  const athDate = new Date('2025-10-06');
  const athPrice = 126296;
  const daysSinceATH = Math.floor((Date.now() - athDate.getTime()) / (1000 * 60 * 60 * 24));
  const avgDaysToBottom = 383;
  const drawdownFromATH = ((currentPrice - athPrice) / athPrice) * 100;
  const cycleProgress = Math.min(daysSinceATH / avgDaysToBottom, 1.0);
  const estimatedBottomDate = new Date(athDate.getTime() + avgDaysToBottom * 24 * 60 * 60 * 1000);

  indicators.cycleTiming = {
    name: 'Cycle Timing',
    athDate: '2025-10-06',
    athPrice,
    daysSinceATH,
    avgDaysToBottom,
    cycleProgress: +cycleProgress.toFixed(4),
    estimatedBottomDate: estimatedBottomDate.toISOString().split('T')[0],
    drawdownPercent: +drawdownFromATH.toFixed(1),
    description: `${daysSinceATH} of ~${avgDaysToBottom} days from ATH to historical average bottom`
  };

  // 3.3 Moving Average Confluence
  const sma50d = sma(dailyPrices, 50);
  const sma100d = sma(dailyPrices, 100);
  const sma200d_val = sma200d;

  // Count how many major MAs price is below (more = more oversold)
  let maBelowCount = 0;
  if (sma50d && currentPrice < sma50d) maBelowCount++;
  if (sma100d && currentPrice < sma100d) maBelowCount++;
  if (sma200d_val && currentPrice < sma200d_val) maBelowCount++;

  indicators.maConfluence = {
    name: 'MA Confluence',
    sma50d: sma50d ? +sma50d.toFixed(2) : null,
    sma100d: sma100d ? +sma100d.toFixed(2) : null,
    sma200d: sma200d_val ? +sma200d_val.toFixed(2) : null,
    belowCount: maBelowCount,
    description: 'Price below multiple major MAs signals deep bearish conditions'
  };

  // ============================
  // DOMAIN 4: SENTIMENT
  // ============================

  // 4.1 Fear & Greed
  let fgCurrent = null;
  let fgAvg30d = null;
  let daysInExtremeFear = 0;

  if (fearGreed && fearGreed.length > 0) {
    fgCurrent = fearGreed[0]; // most recent first

    // 30d average
    const last30 = fearGreed.slice(0, 30).map(f => f.value);
    fgAvg30d = last30.reduce((a, b) => a + b, 0) / last30.length;

    // Count consecutive days in extreme fear (< 25)
    for (const fg of fearGreed) {
      if (fg.value < 25) daysInExtremeFear++;
      else break;
    }
  }

  indicators.fearGreed = {
    name: 'Fear & Greed Index',
    current: fgCurrent ? fgCurrent.value : null,
    label: fgCurrent ? fgCurrent.label : null,
    avg30d: fgAvg30d ? +fgAvg30d.toFixed(1) : null,
    consecutiveExtremeFearDays: daysInExtremeFear,
    thresholds: { extremeFear: 25, fear: 40, neutral: 55, greed: 75, extremeGreed: 90 },
    description: 'Sustained extreme fear (< 25) = contrarian buy signal'
  };

  // 4.2 Funding Rates
  let avgFundingRate = null;
  let currentFundingRate = null;
  let negativeFundingDays = 0;

  if (fundingRates && fundingRates.length > 0) {
    currentFundingRate = fundingRates[fundingRates.length - 1].rate;

    // Average over last 30 entries (~10 days since 3x/day)
    const recent = fundingRates.slice(-30);
    avgFundingRate = recent.reduce((a, b) => a + b.rate, 0) / recent.length;

    // Count negative entries
    negativeFundingDays = recent.filter(f => f.rate < 0).length;
  }

  indicators.fundingRates = {
    name: 'Funding Rates',
    current: currentFundingRate ? +currentFundingRate.toFixed(6) : null,
    avg10d: avgFundingRate ? +avgFundingRate.toFixed(6) : null,
    negativePeriods: negativeFundingDays,
    description: 'Negative funding = shorts paying longs = bearish positioning = contrarian buy'
  };

  // ============================
  // DOMAIN 5: MACRO (limited without FRED, using price-based proxies)
  // ============================

  // We note these as requiring manual update or FRED API key
  indicators.macro = {
    name: 'Macro Liquidity',
    note: 'Macro indicators update slowly. Add FRED API key for automation.',
    fedFundsRate: { value: 3.625, asOf: '2026-03-01', trend: 'easing', description: 'Fed has cut 6 times since Sep 2024' },
    dxy: { value: 97.6, asOf: '2026-03-01', trend: 'stable', description: 'Dollar index - inverse correlation may be breaking' },
    m2YoY: { value: 10.2, asOf: '2026-02-01', trend: 'expanding', description: 'Global M2 growing >10% but BTC diverging (unusual)' },
    realYield10y: { value: 2.1, asOf: '2026-03-01', trend: 'elevated', description: 'Near 15-year highs - headwind for non-yielding assets' },
    creditSpreadHY: { value: 3.2, asOf: '2026-03-01', trend: 'stable', description: 'Near lows but $33T refi wall risk ahead' }
  };

  // ============================
  // DOMAIN 6: LTH / SMART MONEY (estimated / noted)
  // ============================

  indicators.lthBehavior = {
    name: 'Long-Term Holder Behavior',
    note: 'Requires Glassnode or CryptoQuant for precise values',
    lthSopr: { value: 1.013, asOf: '2026-03-01', description: 'Near break-even, briefly dipped below 1.0 in Jan' },
    supplyInProfit: { value: 52, asOf: '2026-03-01', description: '~52% - approaching historic 50% convergence bottom signal' },
    sopr: { value: 0.994, asOf: '2026-03-01', description: 'At break-even threshold' },
    realizedPrice: { value: 54480, asOf: '2026-03-01', description: 'Aggregate cost basis - price 23% above' }
  };

  // ============================
  // COMPOSITE SCORING
  // ============================

  indicators._composite = computeCompositeScore(indicators);
  indicators._meta = {
    computedAt: new Date().toISOString(),
    currentPrice: +currentPrice.toFixed(2),
    currentDate,
    dataSources: [
      'CoinGecko (price, market cap)',
      'Alternative.me (Fear & Greed)',
      'Binance (funding rates)',
      'Blockchain.com (hash rate, miner revenue)'
    ]
  };

  return indicators;
}

// --- Composite Score ---

function computeCompositeScore(ind) {
  const scores = {};

  // DOMAIN 1: On-Chain Valuation (30%)
  const d1Scores = [];

  // Mayer Multiple: 0.6 or below = 10, 0.8 = 7, 1.0 = 3, above 1.5 = 0
  if (ind.mayerMultiple.value !== null) {
    const mm = ind.mayerMultiple.value;
    let s = 0;
    if (mm <= 0.5) s = 10;
    else if (mm <= 0.6) s = 9;
    else if (mm <= 0.7) s = 8;
    else if (mm <= 0.8) s = 7;
    else if (mm <= 0.9) s = 5;
    else if (mm <= 1.0) s = 3;
    else if (mm <= 1.2) s = 1;
    else s = 0;
    d1Scores.push({ name: 'Mayer Multiple', score: s, weight: 2 });
  }

  // 200WMA: at or below = 10, within 10% = 7, within 20% = 4, above 30% = 0
  if (ind.wma200.ratio !== null) {
    const r = ind.wma200.ratio;
    let s = 0;
    if (r <= 0.9) s = 10;
    else if (r <= 1.0) s = 9;
    else if (r <= 1.1) s = 7;
    else if (r <= 1.2) s = 5;
    else if (r <= 1.3) s = 3;
    else if (r <= 1.5) s = 1;
    else s = 0;
    d1Scores.push({ name: '200WMA Proximity', score: s, weight: 2 });
  }

  // MVRV-Z (estimated): below -1 = 10, below 0 = 7, 0-1 = 4, above 2 = 0
  if (ind.mvrvZScore.value !== null) {
    const z = ind.mvrvZScore.value;
    let s = 0;
    if (z <= -1.5) s = 10;
    else if (z <= -1.0) s = 9;
    else if (z <= 0) s = 7;
    else if (z <= 0.5) s = 5;
    else if (z <= 1.0) s = 3;
    else if (z <= 2.0) s = 1;
    else s = 0;
    d1Scores.push({ name: 'MVRV-Z (est)', score: s, weight: 1.5 });
  }

  // Rainbow: Fire Sale = 10, BUY = 8, Accumulate = 5, Still Cheap = 3, HODL = 1
  const bandScores = { 'Fire Sale': 10, 'BUY!': 8, 'Accumulate': 5, 'Still Cheap': 3, 'HODL!': 1 };
  const rainbowScore = bandScores[ind.rainbowChart.currentBand] || 0;
  d1Scores.push({ name: 'Rainbow Chart', score: rainbowScore, weight: 1 });

  // Power Law: ratio < 0.5 = 10, < 0.7 = 7, < 1.0 = 4, > 1.5 = 0
  if (ind.powerLaw.currentRatio !== null) {
    const r = ind.powerLaw.currentRatio;
    let s = 0;
    if (r <= 0.4) s = 10;
    else if (r <= 0.5) s = 9;
    else if (r <= 0.7) s = 7;
    else if (r <= 1.0) s = 4;
    else if (r <= 1.5) s = 1;
    else s = 0;
    d1Scores.push({ name: 'Power Law', score: s, weight: 1 });
  }

  // Supply in Profit (manual): < 50% = 10, 50-55% = 8, 55-60% = 5, > 75% = 0
  const sip = ind.lthBehavior.supplyInProfit.value;
  let sipScore = 0;
  if (sip <= 45) sipScore = 10;
  else if (sip <= 50) sipScore = 9;
  else if (sip <= 55) sipScore = 7;
  else if (sip <= 60) sipScore = 5;
  else if (sip <= 70) sipScore = 3;
  else if (sip <= 80) sipScore = 1;
  else sipScore = 0;
  d1Scores.push({ name: 'Supply in Profit', score: sipScore, weight: 2 });

  // Realized Price proximity (manual)
  const rpRatio = ind._meta?.currentPrice ? ind._meta.currentPrice / ind.lthBehavior.realizedPrice.value : null;
  let rpScore = 0;
  if (rpRatio) {
    if (rpRatio <= 0.8) rpScore = 10;
    else if (rpRatio <= 0.9) rpScore = 9;
    else if (rpRatio <= 1.0) rpScore = 8;
    else if (rpRatio <= 1.1) rpScore = 6;
    else if (rpRatio <= 1.2) rpScore = 4;
    else if (rpRatio <= 1.3) rpScore = 2;
    else rpScore = 0;
  }
  d1Scores.push({ name: 'Realized Price', score: rpScore, weight: 1.5 });

  // DOMAIN 2: Miner Health (15%)
  const d2Scores = [];

  // Hash Ribbon
  let hrScore = 0;
  if (ind.hashRibbon.signal === 'BUY_SIGNAL') hrScore = 10;
  else if (ind.hashRibbon.signal === 'CAPITULATION') hrScore = 7;
  else if (ind.hashRibbon.signal === 'RECOVERY') hrScore = 3;
  else hrScore = 0;
  d2Scores.push({ name: 'Hash Ribbon', score: hrScore, weight: 2 });

  // Puell Multiple
  if (ind.puellMultiple.value !== null) {
    const pm = ind.puellMultiple.value;
    let s = 0;
    if (pm <= 0.3) s = 10;
    else if (pm <= 0.5) s = 8;
    else if (pm <= 0.7) s = 5;
    else if (pm <= 1.0) s = 3;
    else if (pm <= 1.5) s = 1;
    else s = 0;
    d2Scores.push({ name: 'Puell Multiple', score: s, weight: 1.5 });
  }

  // DOMAIN 3: Technical (20%)
  const d3Scores = [];

  // Pi Cycle Bottom
  let pcbScore = 0;
  if (ind.piCycleBottom.signal === 'BOTTOM_ZONE') pcbScore = 10;
  else pcbScore = 2;
  d3Scores.push({ name: 'Pi Cycle Bottom', score: pcbScore, weight: 1.5 });

  // Drawdown from ATH
  const dd = Math.abs(ind.cycleTiming.drawdownPercent);
  let ddScore = 0;
  if (dd >= 80) ddScore = 10;
  else if (dd >= 70) ddScore = 9;
  else if (dd >= 60) ddScore = 7;
  else if (dd >= 50) ddScore = 5;
  else if (dd >= 40) ddScore = 3;
  else if (dd >= 30) ddScore = 1;
  else ddScore = 0;
  d3Scores.push({ name: 'Drawdown Depth', score: ddScore, weight: 1 });

  // MA Confluence (all MAs below = more oversold)
  const macScore = (ind.maConfluence.belowCount / 3) * 10;
  d3Scores.push({ name: 'MA Confluence', score: +macScore.toFixed(0), weight: 1 });

  // DOMAIN 4: Sentiment (15%)
  const d4Scores = [];

  // Fear & Greed
  if (ind.fearGreed.current !== null) {
    const fg = ind.fearGreed.current;
    let s = 0;
    if (fg <= 10) s = 10;
    else if (fg <= 15) s = 9;
    else if (fg <= 20) s = 8;
    else if (fg <= 25) s = 7;
    else if (fg <= 30) s = 5;
    else if (fg <= 40) s = 3;
    else if (fg <= 50) s = 1;
    else s = 0;
    d4Scores.push({ name: 'Fear & Greed', score: s, weight: 2 });
  }

  // Sustained extreme fear duration
  const efDays = ind.fearGreed.consecutiveExtremeFearDays;
  let efScore = 0;
  if (efDays >= 30) efScore = 10;
  else if (efDays >= 21) efScore = 8;
  else if (efDays >= 14) efScore = 6;
  else if (efDays >= 7) efScore = 4;
  else if (efDays >= 3) efScore = 2;
  else efScore = 0;
  d4Scores.push({ name: 'Fear Duration', score: efScore, weight: 1 });

  // Funding Rates
  if (ind.fundingRates.avg10d !== null) {
    const fr = ind.fundingRates.avg10d;
    let s = 0;
    if (fr <= -0.01) s = 10;
    else if (fr <= -0.005) s = 8;
    else if (fr <= -0.001) s = 6;
    else if (fr <= 0) s = 4;
    else if (fr <= 0.005) s = 1;
    else s = 0;
    d4Scores.push({ name: 'Funding Rates', score: s, weight: 1.5 });
  }

  // SOPR (manual)
  const soprVal = ind.lthBehavior.sopr.value;
  let soprScore = 0;
  if (soprVal <= 0.90) soprScore = 10;
  else if (soprVal <= 0.95) soprScore = 8;
  else if (soprVal <= 0.98) soprScore = 6;
  else if (soprVal <= 1.00) soprScore = 5;
  else if (soprVal <= 1.02) soprScore = 3;
  else soprScore = 0;
  d4Scores.push({ name: 'SOPR', score: soprScore, weight: 1.5 });

  // DOMAIN 5: Macro (10%)
  const d5Scores = [];

  // Fed: easing = good, tightening = bad
  const fedTrend = ind.macro.fedFundsRate.trend;
  let fedScore = fedTrend === 'easing' ? 7 : (fedTrend === 'stable' ? 4 : 1);
  d5Scores.push({ name: 'Fed Policy', score: fedScore, weight: 1 });

  // M2: expanding = good (normally), but currently diverging
  const m2Score = ind.macro.m2YoY.value > 5 ? 5 : 2; // discount due to divergence
  d5Scores.push({ name: 'Global M2', score: m2Score, weight: 1 });

  // Real yields: high = bad for BTC
  const ryVal = ind.macro.realYield10y.value;
  let ryScore = 0;
  if (ryVal <= 0) ryScore = 9;
  else if (ryVal <= 0.5) ryScore = 7;
  else if (ryVal <= 1.0) ryScore = 5;
  else if (ryVal <= 1.5) ryScore = 3;
  else if (ryVal <= 2.0) ryScore = 1;
  else ryScore = 0;
  d5Scores.push({ name: 'Real Yields', score: ryScore, weight: 1 });

  // DOMAIN 6: Cycle Timing (10%)
  const d6Scores = [];

  // Cycle progress (further into typical bottom window = higher score)
  const cp = ind.cycleTiming.cycleProgress;
  let cpScore = 0;
  if (cp >= 0.95) cpScore = 10;
  else if (cp >= 0.85) cpScore = 9;
  else if (cp >= 0.75) cpScore = 7;
  else if (cp >= 0.60) cpScore = 5;
  else if (cp >= 0.40) cpScore = 3;
  else if (cp >= 0.25) cpScore = 1;
  else cpScore = 0;
  d6Scores.push({ name: 'Cycle Progress', score: cpScore, weight: 2 });

  // LTH-SOPR (manual)
  const lthSopr = ind.lthBehavior.lthSopr.value;
  let lthScore = 0;
  if (lthSopr <= 0.90) lthScore = 10;
  else if (lthSopr <= 0.95) lthScore = 9;
  else if (lthSopr <= 1.00) lthScore = 8;
  else if (lthSopr <= 1.05) lthScore = 5;
  else if (lthSopr <= 1.20) lthScore = 2;
  else lthScore = 0;
  d6Scores.push({ name: 'LTH-SOPR', score: lthScore, weight: 1.5 });

  // Calculate weighted domain scores
  function domainScore(items) {
    if (items.length === 0) return 0;
    let totalWeight = 0;
    let totalScore = 0;
    for (const item of items) {
      totalScore += item.score * item.weight;
      totalWeight += item.weight;
    }
    return totalWeight > 0 ? totalScore / totalWeight : 0;
  }

  const domains = {
    onChainValuation: { score: +domainScore(d1Scores).toFixed(1), weight: 0.30, items: d1Scores, label: 'On-Chain Valuation' },
    minerHealth: { score: +domainScore(d2Scores).toFixed(1), weight: 0.15, items: d2Scores, label: 'Miner Health' },
    technical: { score: +domainScore(d3Scores).toFixed(1), weight: 0.20, items: d3Scores, label: 'Technical / Price' },
    sentiment: { score: +domainScore(d4Scores).toFixed(1), weight: 0.15, items: d4Scores, label: 'Sentiment & Positioning' },
    macro: { score: +domainScore(d5Scores).toFixed(1), weight: 0.10, items: d5Scores, label: 'Macro Liquidity' },
    cycleTiming: { score: +domainScore(d6Scores).toFixed(1), weight: 0.10, items: d6Scores, label: 'Cycle Timing & Smart Money' }
  };

  // Composite = weighted sum of domain scores, scaled to 0-100
  let composite = 0;
  for (const d of Object.values(domains)) {
    composite += d.score * d.weight;
  }
  composite = composite * 10; // scale 0-10 domain scores to 0-100

  // Zone classification
  let zone, zoneLabel, zoneColor;
  if (composite >= 75) { zone = 'STRONG_BUY'; zoneLabel = 'STRONG BUY'; zoneColor = '#22C55E'; }
  else if (composite >= 50) { zone = 'ACCUMULATE'; zoneLabel = 'ACCUMULATE'; zoneColor = '#F59E0B'; }
  else if (composite >= 25) { zone = 'WATCHING'; zoneLabel = 'WATCHING'; zoneColor = '#FB923C'; }
  else { zone = 'NO_ENTRY'; zoneLabel = 'NO ENTRY'; zoneColor = '#EF4444'; }

  return {
    score: +composite.toFixed(1),
    zone,
    zoneLabel,
    zoneColor,
    domains
  };
}

// --- Main ---

async function main() {
  console.log('╔══════════════════════════════════════════╗');
  console.log('║  Bitcoin Re-Entry Signal — Data Engine   ║');
  console.log('╚══════════════════════════════════════════╝');

  if (!existsSync(DATA_DIR)) mkdirSync(DATA_DIR, { recursive: true });

  // Fetch all data in parallel where possible
  const [priceHistory, fearGreed, fundingRates, hashRate, minerRevenue] = await Promise.all([
    fetchPriceHistory(),
    fetchFearGreed(),
    fetchFundingRates(),
    fetchHashRate(),
    fetchMinerRevenue()
  ]);

  if (!priceHistory) {
    console.error('\n❌ Failed to fetch price history — cannot compute indicators');
    process.exit(1);
  }

  // Compute all indicators
  const indicators = computeIndicators(priceHistory, fearGreed, fundingRates, hashRate, minerRevenue);

  // Save
  const outPath = join(DATA_DIR, 'indicators.json');
  writeFileSync(outPath, JSON.stringify(indicators, null, 2));
  console.log(`\n💾 Saved to ${outPath}`);

  // Summary
  const c = indicators._composite;
  console.log('\n╔══════════════════════════════════════════╗');
  console.log(`║  COMPOSITE SCORE: ${c.score.toString().padStart(5)}  [${c.zoneLabel}]`.padEnd(43) + '║');
  console.log('╠══════════════════════════════════════════╣');
  for (const [key, domain] of Object.entries(c.domains)) {
    const pct = (domain.weight * 100).toFixed(0);
    console.log(`║  ${domain.label.padEnd(28)} ${domain.score.toFixed(1).padStart(4)}/10  (${pct}%)  ║`);
  }
  console.log('╚══════════════════════════════════════════╝');
}

main().catch(e => { console.error(e); process.exit(1); });
