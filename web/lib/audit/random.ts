import MersenneTwister from "mersenne-twister";

export class PythonRandom {
  private m: MersenneTwister;

  constructor(seed: bigint | number) {
    // Seed initialization matching python's random.seed(int) behavior (array of 32-bit LE chunks)
    if (typeof seed === "number") seed = BigInt(seed);
    const chunks = [];
    let current = seed < 0n ? -seed : seed; // Python handles negatives, though derived seeds are +ve
    
    if (current === 0n) {
      chunks.push(0);
    } else {
      while (current > 0n) {
        chunks.push(Number(current & 0xFFFFFFFFn));
        current >>= 32n;
      }
    }
    this.m = new MersenneTwister(chunks);
  }

  getRandBits(k: number): number {
    if (k === 0) return 0;
    if (k > 32) throw new Error("getRandBits>32 not implemented");
    return this.m.random_int() >>> (32 - k);
  }

  randBelow(n: number): number {
    if (n <= 0) throw new Error("n must be > 0");
    const bitLength = n.toString(2).length;
    let r = this.getRandBits(bitLength);
    while (r >= n) {
      r = this.getRandBits(bitLength);
    }
    return r;
  }

  shuffle<T>(x: T[]): void {
    for (let i = x.length - 1; i > 0; i--) {
      const j = this.randBelow(i + 1);
      const temp = x[i];
      x[i] = x[j];
      x[j] = temp;
    }
  }
}
