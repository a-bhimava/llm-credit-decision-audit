import { AuditPreflight } from "@/lib/audit/contracts";
import { redis } from "@/lib/audit/redis";

export class BudgetExceeded extends Error {
  public spent: BudgetState;
  constructor(message: string, spent: BudgetState) {
    super(message);
    this.name = "BudgetExceeded";
    this.spent = spent;
  }
}

export interface BudgetState {
  episodes: number;
  usd: number;
  inputTokens: number;
  outputTokens: number;
  cachedTokens: number;
  thoughtTokens: number;
  cacheHits: number;
  replayed: number;
  elapsedSeconds: number;
  totalTokens: number;
}

export interface Usage {
  costUsd: number;
  inputTokens: number;
  outputTokens: number;
  cachedTokens: number;
  thoughtTokens: number;
  cacheHit: boolean;
  replayed: boolean;
}

export class Budget {
  private preflight: AuditPreflight;
  private started: number;
  private _episodes = 0;
  private _usd = 0;
  private _inputTokens = 0;
  private _outputTokens = 0;
  private _cachedTokens = 0;
  private _thoughtTokens = 0;
  private _cacheHits = 0;
  private _replayed = 0;
  private _billableTokens = 0;

  constructor(preflight: AuditPreflight, clock: () => number = () => performance.now() / 1000) {
    this.preflight = preflight;
    this.started = clock();
  }

  public state(clock: () => number = () => performance.now() / 1000): BudgetState {
    return {
      episodes: this._episodes,
      usd: this._usd,
      inputTokens: this._inputTokens,
      outputTokens: this._outputTokens,
      cachedTokens: this._cachedTokens,
      thoughtTokens: this._thoughtTokens,
      cacheHits: this._cacheHits,
      replayed: this._replayed,
      elapsedSeconds: clock() - this.started,
      totalTokens: this._inputTokens + this._outputTokens,
    };
  }

  public admit(plannedEpisodes: number) {
    const cap = this.preflight.plannedEpisodesUpper;
    if (cap !== undefined && plannedEpisodes > cap) {
      throw new BudgetExceeded(
        `plan needs up to ${plannedEpisodes} episodes but the preflight caps them at ${cap}`,
        this.state()
      );
    }
  }

  private _usdPerConfig: Record<string, number> = {};

  public charge(usage: Usage, configurationId: string = "default") {
    if (usage.costUsd === undefined || isNaN(usage.costUsd) || usage.costUsd < 0) {
      throw new BudgetExceeded("rejected unpriced model", this.state());
    }

    this._episodes++;
    this._usd += usage.costUsd;
    this._usdPerConfig[configurationId] = (this._usdPerConfig[configurationId] || 0) + usage.costUsd;
    this._inputTokens += usage.inputTokens;
    this._outputTokens += usage.outputTokens;
    this._cachedTokens += usage.cachedTokens;
    this._thoughtTokens += usage.thoughtTokens;
    if (usage.cacheHit) this._cacheHits++;
    if (usage.replayed) this._replayed++;
    
    if (!usage.replayed) {
      this._billableTokens += usage.inputTokens + usage.outputTokens;
    }
    
    this.enforce(configurationId);
  }

  private enforce(lastConfig?: string) {
    const capUsd = this.preflight.jobUsdCap;
    if (capUsd !== undefined && this._usd > capUsd) {
      throw new BudgetExceeded(`cost cap reached: ${this._usd.toFixed(4)} > ${capUsd.toFixed(4)}`, this.state());
    }
    const configCap = this.preflight.perConfigurationUsdCap;
    if (configCap !== undefined && lastConfig && this._usdPerConfig[lastConfig] > configCap) {
      throw new BudgetExceeded(`configuration cost cap reached for ${lastConfig}: ${this._usdPerConfig[lastConfig].toFixed(4)} > ${configCap.toFixed(4)}`, this.state());
    }
    const capEpisodes = this.preflight.plannedEpisodesUpper;
    if (capEpisodes !== undefined && this._episodes > capEpisodes) {
      throw new BudgetExceeded(`episode cap reached: ${this._episodes} > ${capEpisodes}`, this.state());
    }
  }

  public async reserveDailyBudget(): Promise<void> {
    const today = new Date().toISOString().split("T")[0];
    const key = `budget:daily:${today}`;
    const amountStr = this.preflight.estimatedUsdUpper.toString();
    const capStr = this.preflight.dailyUsdCap.toString();

    // Lua script to atomically increment and check bounds
    const script = `
      local key = KEYS[1]
      local amount = tonumber(ARGV[1])
      local cap = tonumber(ARGV[2])
      
      local current = tonumber(redis.call('GET', key) or "0")
      local after = current + amount
      
      if after > cap then
        return { 0, tostring(current) }
      else
        redis.call('SET', key, tostring(after), 'EX', 86400 * 2)
        return { 1, tostring(after) }
      end
    `;

    const result = await redis.eval<[number, string]>(script, [key], [amountStr, capStr]);
    const [success, totalStr] = result;
    
    if (success === 0) {
      const current = parseFloat(totalStr);
      throw new Error(`Daily budget exhausted. Requesting $${amountStr}, but current spend is $${current.toFixed(2)} (cap: $${capStr}).`);
    }
  }
}
