declare module 'mersenne-twister' {
  export default class MersenneTwister {
    constructor(seed?: number | number[] | bigint);
    random(): number;
    random_int(): number;
    random_excl(): number;
    random_long(): number;
    random_incl(): number;
  }
}
