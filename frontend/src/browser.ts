/** Qual navegador abriu o app, para orientar a instalação. Detecção por user agent: é só uma dica, nunca bloqueia nada. */
export type BrowserKind =
  | "in-app" // navegador interno do WhatsApp, Instagram, Facebook, Telegram, Gmail...
  | "ios-safari"
  | "ios-other" // Chrome, Firefox ou Edge no iPhone
  | "android-chrome"
  | "android-samsung"
  | "android-firefox"
  | "android-other"
  | "desktop";

export function browserKind(ua = navigator.userAgent): BrowserKind {
  const ios = /iphone|ipad|ipod/i.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
  const android = /android/i.test(ua);
  if (/FBAN|FBAV|FB_IAB|Instagram|WhatsApp|Line\/|Telegram|LinkedInApp|Snapchat|TikTok|musical_ly|GSA\//i.test(ua)) return "in-app";
  if (android && /; wv\)/.test(ua)) return "in-app"; // WebView do Android (apps que abrem links por dentro)
  if (ios) {
    if (/CriOS|FxiOS|EdgiOS|OPiOS/.test(ua)) return "ios-other";
    if (!/Safari\//.test(ua)) return "in-app"; // WebView do iOS não tem "Safari/" no user agent
    return "ios-safari";
  }
  if (android) {
    if (/SamsungBrowser/.test(ua)) return "android-samsung";
    if (/Firefox/.test(ua)) return "android-firefox";
    if (/Chrome\//.test(ua) && !/EdgA|OPR|YaBrowser|MiuiBrowser|HeyTap|UCBrowser/.test(ua)) return "android-chrome";
    return "android-other";
  }
  return "desktop";
}

/** Link que abre este endereço direto no Chrome do Android (funciona a partir do WhatsApp e de outros navegadores internos). */
export function chromeIntentUrl(href = window.location.href): string {
  const u = new URL(href);
  return `intent://${u.host}${u.pathname}${u.search}#Intent;scheme=${u.protocol.replace(":", "")};package=com.android.chrome;end`;
}
