import fs from "fs";
import path from "path";
import { ModelClient, ModelRequest, ModelResponse } from "./client";
import { cacheKey } from "./cache";

export class CassetteClient implements ModelClient {
  public modelId: string;
  private cassette: Record<string, ModelResponse>;

  constructor(cassetteName: string, modelId: string) {
    this.modelId = modelId;
    const filepath = path.join(process.cwd(), "tests/fixtures/cassettes", `${cassetteName}.json`);
    this.cassette = JSON.parse(fs.readFileSync(filepath, "utf8"));
  }

  async complete(req: ModelRequest): Promise<ModelResponse> {
    const key = cacheKey(req);
    const resp = this.cassette[key];
    if (!resp) {
      throw new Error(`Cassette miss for key ${key}`);
    }
    return resp;
  }
}
