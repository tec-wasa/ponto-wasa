import { describe, expect, it } from "vitest";
import { browserKind, chromeIntentUrl } from "./browser";

const UA = {
  whatsappAndroid: "Mozilla/5.0 (Linux; Android 13; SM-A135M Build/TP1A; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0 Mobile Safari/537.36",
  instagramIos: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 309.0",
  iosWebview: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
  safari: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1",
  chromeIos: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/120.0 Mobile/15E148 Safari/604.1",
  chromeAndroid: "Mozilla/5.0 (Linux; Android 13; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36",
  samsung: "Mozilla/5.0 (Linux; Android 13; SM-A135M) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/23.0 Chrome/115.0 Mobile Safari/537.36",
  miui: "Mozilla/5.0 (Linux; Android 12; M2101K6G) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0 Mobile Safari/537.36 XiaoMi/MiuiBrowser/17.0",
  desktop: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
};

describe("browserKind", () => {
  it("reconhece navegadores internos e os comuns", () => {
    expect(browserKind(UA.whatsappAndroid)).toBe("in-app");
    expect(browserKind(UA.instagramIos)).toBe("in-app");
    expect(browserKind(UA.iosWebview)).toBe("in-app");
    expect(browserKind(UA.safari)).toBe("ios-safari");
    expect(browserKind(UA.chromeIos)).toBe("ios-other");
    expect(browserKind(UA.chromeAndroid)).toBe("android-chrome");
    expect(browserKind(UA.samsung)).toBe("android-samsung");
    expect(browserKind(UA.miui)).toBe("android-other");
    expect(browserKind(UA.desktop)).toBe("desktop");
  });

  it("monta o link que abre no Chrome", () => {
    expect(chromeIntentUrl("https://ponto.exemplo.com.br/mais?x=1"))
      .toBe("intent://ponto.exemplo.com.br/mais?x=1#Intent;scheme=https;package=com.android.chrome;end");
  });
});
