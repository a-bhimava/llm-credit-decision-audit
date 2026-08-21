"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.Ratio = void 0;
exports.assertCents = assertCents;
class Ratio {
    value;
    constructor(value) {
        this.value = value;
    }
    static fromNumber(val) {
        if (isNaN(val) || !isFinite(val))
            throw new TypeError("Ratio must be a finite number");
        return new Ratio(Math.round(val * 10000));
    }
    static fromFraction(numerator, denominator) {
        if (denominator === 0)
            throw new TypeError("Division by zero");
        return new Ratio(Math.round((numerator / denominator) * 10000));
    }
    static fromPercent(percent) {
        return new Ratio(Math.round(percent * 100));
    }
    toNumber() {
        return this.value / 10000;
    }
    toString() {
        return this.toNumber().toFixed(4);
    }
    toJSON() {
        return this.toNumber();
    }
    eq(other) { return this.value === other.value; }
    gt(other) { return this.value > other.value; }
    gte(other) { return this.value >= other.value; }
    lt(other) { return this.value < other.value; }
    lte(other) { return this.value <= other.value; }
}
exports.Ratio = Ratio;
function assertCents(val) {
    if (!Number.isSafeInteger(val)) {
        throw new TypeError(`Cents must be a safe integer, got ${val}`);
    }
    return val;
}
