export class Ratio {
  private readonly value: number;

  private constructor(value: number) {
    this.value = value;
  }

  static fromNumber(val: number): Ratio {
    if (isNaN(val) || !isFinite(val)) throw new TypeError("Ratio must be a finite number");
    return new Ratio(Math.round(val * 10000));
  }

  static fromFraction(numerator: number, denominator: number): Ratio {
    if (denominator === 0) throw new TypeError("Division by zero");
    return new Ratio(Math.round((numerator / denominator) * 10000));
  }
  
  static fromPercent(percent: number): Ratio {
    return new Ratio(Math.round(percent * 100));
  }

  toNumber(): number {
    return this.value / 10000;
  }

  toString(): string {
    return this.toNumber().toFixed(4);
  }
  
  toJSON(): number {
    return this.toNumber();
  }
  
  eq(other: Ratio): boolean { return this.value === other.value; }
  gt(other: Ratio): boolean { return this.value > other.value; }
  gte(other: Ratio): boolean { return this.value >= other.value; }
  lt(other: Ratio): boolean { return this.value < other.value; }
  lte(other: Ratio): boolean { return this.value <= other.value; }
}

export function assertCents(val: number): number {
  if (!Number.isSafeInteger(val)) {
    throw new TypeError(`Cents must be a safe integer, got ${val}`);
  }
  return val;
}
