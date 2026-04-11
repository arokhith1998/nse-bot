"use client";

import { BookOpen, TrendingUp, Shield, IndianRupee, BarChart2, AlertTriangle, CheckCircle, ArrowRight } from "lucide-react";

function Section({ icon: Icon, title, children }: { icon: React.ElementType; title: string; children: React.ReactNode }) {
  return (
    <div className="bg-card border border-line rounded-xl p-6">
      <div className="flex items-center gap-2.5 mb-4">
        <Icon className="w-5 h-5 text-accent" />
        <h2 className="text-sm font-semibold text-ink">{title}</h2>
      </div>
      <div className="text-sm text-mute leading-relaxed space-y-3">
        {children}
      </div>
    </div>
  );
}

function Term({ word, children }: { word: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3 py-2 border-b border-line/50 last:border-0">
      <span className="text-accent font-medium shrink-0 w-32">{word}</span>
      <span>{children}</span>
    </div>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-4">
      <div className="w-7 h-7 rounded-full bg-accent/20 text-accent text-xs font-bold flex items-center justify-center shrink-0 mt-0.5">
        {n}
      </div>
      <div>
        <p className="text-ink font-medium mb-1">{title}</p>
        <p className="text-mute">{children}</p>
      </div>
    </div>
  );
}

export default function GuidePage() {
  return (
    <div className="space-y-5 max-w-3xl">
      <div>
        <h1 className="text-lg font-semibold text-ink">Beginner&apos;s Guide</h1>
        <p className="text-xs text-mute mt-1">
          Everything you need to understand this platform, even with zero trading experience.
        </p>
      </div>

      {/* What is this platform */}
      <Section icon={BookOpen} title="What Is This Platform?">
        <p>
          This is a <strong className="text-ink">daily stock suggestion engine</strong> for the Indian stock market (NSE).
          Every morning, it scans hundreds of stocks and tells you which ones look promising for that day.
        </p>
        <p>
          Think of it as a smart assistant that says: <em>&quot;Based on your budget, here are the stocks worth looking at today, and why.&quot;</em>
        </p>
        <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3 text-xs text-red-400">
          <strong>Important:</strong> This is paper trading only. No real money is involved. No orders are placed.
          Use it to learn, practice, and build confidence before trading with real money on platforms like Groww or Zerodha.
        </div>
      </Section>

      {/* Key terms */}
      <Section icon={BookOpen} title="Key Terms Explained">
        <Term word="Stock / Share">A tiny piece of ownership in a company. When you buy 1 share of Reliance, you own a small part of Reliance Industries.</Term>
        <Term word="NSE">National Stock Exchange of India. It&apos;s where stocks are bought and sold. Open 9:15 AM to 3:30 PM IST, Monday to Friday.</Term>
        <Term word="Intraday">Buying and selling a stock on the same day. You don&apos;t hold it overnight. This platform focuses on intraday suggestions.</Term>
        <Term word="Entry Price">The price at which you should buy the stock. The platform suggests an &quot;entry zone&quot; (a range) rather than an exact price.</Term>
        <Term word="Stop Loss (SL)">A safety net. If the stock drops to this price, you sell immediately to limit your loss. Never trade without one.</Term>
        <Term word="Target">The price where you take your profit. When the stock reaches this price, you sell.</Term>
        <Term word="Risk:Reward (R:R)">How much you stand to gain vs. how much you might lose. An R:R of 2.0 means you could gain Rs 2 for every Rs 1 you risk. Higher is better. Look for at least 1.5.</Term>
        <Term word="Score">A number from 0 to 100. The platform scores each stock based on multiple factors (trend, momentum, volume, etc.). Higher score = stronger signal.</Term>
        <Term word="Regime">The overall market mood. &quot;Trend Up&quot; means the market is rising. &quot;Range Chop&quot; means it&apos;s moving sideways. The platform adjusts its suggestions based on the regime.</Term>
        <Term word="Capital">The total amount of money you have available to trade with. This is the most important input you give the platform.</Term>
        <Term word="Qty">Quantity -- how many shares the platform suggests you buy. This is calculated based on your capital and risk limits.</Term>
        <Term word="Bias">Direction. &quot;LONG&quot; means buy (expecting the price to go up). This platform only suggests long trades.</Term>
      </Section>

      {/* How to use */}
      <Section icon={ArrowRight} title="How to Use This Platform (Step by Step)">
        <div className="space-y-4">
          <Step n={1} title="Set your capital">
            On the Dashboard, enter how much money you have for trading in the &quot;Your Capital&quot; field and click &quot;Update Picks&quot;. The platform adjusts how many stocks it suggests based on your budget.
          </Step>
          <Step n={2} title="Check the regime">
            Look at the Regime Panel at the top of the Dashboard. It tells you the market mood. In &quot;Trend Down&quot; or &quot;High Vol&quot; regimes, the platform is more cautious and suggests fewer trades.
          </Step>
          <Step n={3} title="Review the picks">
            The Picks table shows today&apos;s suggestions. Each pick has a score, entry zone, stop loss, target, and quantity. Click a row to see more details.
          </Step>
          <Step n={4} title="Read the advisory">
            The yellow advisory box above the picks gives you context: how many picks to focus on, which ones are high-confidence, and if any are correlated (don&apos;t buy both).
          </Step>
          <Step n={5} title="Simulate the trade">
            On a real platform (Groww/Zerodha), you would place a buy order at the entry price, set a stop loss, and set a target sell order. Here, just track it mentally or on paper.
          </Step>
          <Step n={6} title="Check back during the day">
            The platform refreshes every 15 minutes during market hours. Come back to see if conditions have changed.
          </Step>
          <Step n={7} title="Review performance">
            Go to the Performance page to see how past suggestions performed. Over time, the system learns from its wins and losses to improve.
          </Step>
        </div>
      </Section>

      {/* Understanding the picks table */}
      <Section icon={TrendingUp} title="Reading the Picks Table">
        <p>Each row in the picks table represents one stock suggestion. Here&apos;s what each column means:</p>
        <div className="overflow-x-auto mt-2">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-line text-left text-mute/70">
                <th className="pb-2 pr-4 font-medium">Column</th>
                <th className="pb-2 font-medium">What It Means</th>
              </tr>
            </thead>
            <tbody className="text-mute">
              <tr className="border-b border-line/50"><td className="py-2 pr-4 text-accent font-medium">Score</td><td className="py-2">Overall strength (0-100). Above 70 is strong.</td></tr>
              <tr className="border-b border-line/50"><td className="py-2 pr-4 text-accent font-medium">Symbol</td><td className="py-2">The stock ticker (e.g., RELIANCE, TCS, INFY).</td></tr>
              <tr className="border-b border-line/50"><td className="py-2 pr-4 text-accent font-medium">Bias</td><td className="py-2">LONG = buy expecting price to rise.</td></tr>
              <tr className="border-b border-line/50"><td className="py-2 pr-4 text-accent font-medium">Setup</td><td className="py-2">The pattern detected (Breakout, Momentum, Pullback, etc.).</td></tr>
              <tr className="border-b border-line/50"><td className="py-2 pr-4 text-accent font-medium">Entry Zone</td><td className="py-2">The price range where you should buy.</td></tr>
              <tr className="border-b border-line/50"><td className="py-2 pr-4 text-accent font-medium">Stop</td><td className="py-2">Your maximum loss price. Sell here if it goes wrong.</td></tr>
              <tr className="border-b border-line/50"><td className="py-2 pr-4 text-accent font-medium">Target</td><td className="py-2">Your profit-taking price. Sell here if it goes right.</td></tr>
              <tr className="border-b border-line/50"><td className="py-2 pr-4 text-accent font-medium">Qty</td><td className="py-2">How many shares to buy, calculated from your capital.</td></tr>
              <tr><td className="py-2 pr-4 text-accent font-medium">R:R</td><td className="py-2">Risk-to-reward ratio. 2.0 means you gain Rs 2 per Rs 1 risked.</td></tr>
            </tbody>
          </table>
        </div>
      </Section>

      {/* Capital guide */}
      <Section icon={IndianRupee} title="How Capital Affects Your Picks">
        <p>The platform adjusts everything based on your capital:</p>
        <div className="overflow-x-auto mt-2">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-line text-left text-mute/70">
                <th className="pb-2 pr-4 font-medium">Your Capital</th>
                <th className="pb-2 pr-4 font-medium">Picks Shown</th>
                <th className="pb-2 font-medium">Why</th>
              </tr>
            </thead>
            <tbody className="text-mute">
              <tr className="border-b border-line/50"><td className="py-2 pr-4 font-medium">Up to Rs 10,000</td><td className="py-2 pr-4">2 picks</td><td className="py-2">Small capital = focus on your best bets only</td></tr>
              <tr className="border-b border-line/50"><td className="py-2 pr-4 font-medium">Rs 10K - 25K</td><td className="py-2 pr-4">3 picks</td><td className="py-2">Enough for a few well-sized positions</td></tr>
              <tr className="border-b border-line/50"><td className="py-2 pr-4 font-medium">Rs 25K - 50K</td><td className="py-2 pr-4">5 picks</td><td className="py-2">Good diversification without over-spreading</td></tr>
              <tr className="border-b border-line/50"><td className="py-2 pr-4 font-medium">Rs 50K - 1 Lakh</td><td className="py-2 pr-4">6 picks</td><td className="py-2">Standard portfolio size</td></tr>
              <tr className="border-b border-line/50"><td className="py-2 pr-4 font-medium">Rs 1L - 2 Lakh</td><td className="py-2 pr-4">8 picks</td><td className="py-2">Well-diversified across sectors</td></tr>
              <tr><td className="py-2 pr-4 font-medium">Rs 2 Lakh+</td><td className="py-2 pr-4">10 picks</td><td className="py-2">Maximum diversification</td></tr>
            </tbody>
          </table>
        </div>
        <p>
          Stocks that cost more than 30% of your capital are automatically filtered out.
          For example, with Rs 5,000 capital, a stock priced at Rs 2,000+ per share won&apos;t show up.
        </p>
      </Section>

      {/* Risk management */}
      <Section icon={Shield} title="Risk Management (The Most Important Section)">
        <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-3 text-xs text-yellow-400 mb-3">
          SEBI data shows ~70% of retail intraday traders lose money. The #1 reason is poor risk management, not bad stock picks.
        </div>
        <div className="space-y-3">
          <div className="flex items-start gap-2">
            <CheckCircle className="w-4 h-4 text-green-400 shrink-0 mt-0.5" />
            <p><strong className="text-ink">Always use a stop loss.</strong> Every pick shows a stop loss price. If you ignore it and &quot;hope&quot; the stock will recover, you will eventually take a devastating loss.</p>
          </div>
          <div className="flex items-start gap-2">
            <CheckCircle className="w-4 h-4 text-green-400 shrink-0 mt-0.5" />
            <p><strong className="text-ink">Risk only 1% per trade.</strong> If you have Rs 50,000, risk at most Rs 500 on any single trade. This means your stop loss should represent a Rs 500 loss at most.</p>
          </div>
          <div className="flex items-start gap-2">
            <CheckCircle className="w-4 h-4 text-green-400 shrink-0 mt-0.5" />
            <p><strong className="text-ink">Never trade more than you can afford to lose.</strong> Use money you don&apos;t need for rent, food, or emergencies.</p>
          </div>
          <div className="flex items-start gap-2">
            <CheckCircle className="w-4 h-4 text-green-400 shrink-0 mt-0.5" />
            <p><strong className="text-ink">Start with paper trading.</strong> This platform is designed for exactly that. Practice for at least 2-3 months before using real money.</p>
          </div>
          <div className="flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
            <p><strong className="text-ink">Don&apos;t chase losses.</strong> If you have a bad day, do NOT increase your position sizes to &quot;make it back&quot;. Take a break. Come back tomorrow.</p>
          </div>
        </div>
      </Section>

      {/* Pages guide */}
      <Section icon={BarChart2} title="Platform Pages Explained">
        <div className="space-y-3">
          <div>
            <p className="text-ink font-medium">Dashboard</p>
            <p>Your home screen. Shows today&apos;s picks, market regime, active trades, news, and risk gauges. Set your capital here.</p>
          </div>
          <div>
            <p className="text-ink font-medium">Regime</p>
            <p>Shows the current market mood in detail. Includes NIFTY/SENSEX levels, VIX (fear index), advance-decline ratio, and sector leaders/laggards.</p>
          </div>
          <div>
            <p className="text-ink font-medium">Trades</p>
            <p>Shows all active and historical trades. Each trade shows entry, exit, P&amp;L, and how long it was held.</p>
          </div>
          <div>
            <p className="text-ink font-medium">Performance</p>
            <p>Shows how the system has performed over time: win rate, profit factor, Sharpe ratio, and breakdown by setup type.</p>
          </div>
          <div>
            <p className="text-ink font-medium">Settings</p>
            <p>Configure your capital, risk per trade, maximum positions, preferred setup types, and notification preferences.</p>
          </div>
        </div>
      </Section>

      {/* FAQ */}
      <Section icon={BookOpen} title="Common Questions">
        <div className="space-y-3">
          <div>
            <p className="text-ink font-medium">Can I lose money using this?</p>
            <p>Not directly -- this is paper trading only. No real orders are placed. But if you later trade with real money based on these suggestions, yes, you can lose money. Always use stop losses.</p>
          </div>
          <div>
            <p className="text-ink font-medium">Why are picks different at different times?</p>
            <p>The market moves constantly. The platform re-scans every 15 minutes during market hours. Prices change, and so do the suggestions.</p>
          </div>
          <div>
            <p className="text-ink font-medium">What broker should I use?</p>
            <p>This platform calculates costs for Groww (flat Rs 20/order) and Zerodha (0.03% or Rs 20, whichever is lower). Both are good for beginners.</p>
          </div>
          <div>
            <p className="text-ink font-medium">What does the score actually measure?</p>
            <p>It combines 6 factors: Trend (is the stock going up?), Momentum (how strong is the move?), Volume (are people actually trading it?), Breakout (is it near a high?), Volatility (is it moving enough to profit?), and News (any recent catalyst?).</p>
          </div>
          <div>
            <p className="text-ink font-medium">How much capital do I need to start?</p>
            <p>You can start paper trading with any amount. For real trading, Rs 10,000 is a reasonable minimum for intraday equity, though Rs 25,000-50,000 gives better diversification.</p>
          </div>
        </div>
      </Section>

      <div className="bg-red-500/5 border border-red-500/20 rounded-xl p-4 text-xs text-red-400/80 leading-relaxed">
        <strong>DISCLAIMER:</strong> This platform is for educational purposes only. It does not constitute investment advice.
        Past performance does not guarantee future results. Always do your own research before trading with real money.
        SEBI registered investment advisors are the appropriate professionals for personalized financial advice.
      </div>
    </div>
  );
}
