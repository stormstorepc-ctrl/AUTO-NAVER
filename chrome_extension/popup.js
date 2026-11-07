// Runs only when the user clicks the extension button. Reads the active tab once, sends to the local app.
const APP = "http://127.0.0.1:8765";
const $ = (id) => document.getElementById(id);
const show = (msg, cls) => { $("status").textContent = msg; $("status").className = cls || ""; };
let reviewUrl = "";

const MESSAGES = {
  login_required: "타오바오 로그인 화면입니다. 직접 로그인한 뒤 상품 페이지에서 다시 누르세요.",
  captcha: "보안 확인 화면입니다. 직접 확인을 마친 뒤 다시 누르세요.",
  no_product: "상품 정보를 찾지 못했습니다. 상품 상세 페이지가 다 열린 뒤 다시 누르세요.",
};

async function loadToken() {
  const { token } = await chrome.storage.local.get("token");
  $("token").value = token || "";
  if (!token) $("setup").open = true;
  return token || "";
}

$("save").addEventListener("click", async () => {
  await chrome.storage.local.set({ token: $("token").value.trim() });
  show("연결 코드를 저장했습니다.", "ok");
});

$("open").addEventListener("click", () => { if (reviewUrl) chrome.tabs.create({ url: reviewUrl }); });

$("capture").addEventListener("click", async () => {
  $("open").hidden = true;
  const token = await loadToken();
  if (!token) { show("먼저 연결 코드를 저장하세요.", "err"); return; }
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  let host = "";
  try { host = new URL(tab.url).hostname; } catch (e) { /* not a web page */ }
  if (!/(^|\.)(taobao|tmall)\.com$/.test(host)) {
    show("타오바오 또는 티몰 상품 페이지에서 눌러주세요.", "err");
    return;
  }
  show("화면을 읽는 중...");
  let data;
  try {
    const [res] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["extract.js"] });
    data = res && res.result;
  } catch (e) {
    show("이 탭을 읽을 수 없습니다: " + e.message, "err");
    return;
  }
  if (!data) { show("화면을 읽지 못했습니다. 페이지를 새로고침한 뒤 다시 누르세요.", "err"); return; }
  if (data.status !== "ok") { show(MESSAGES[data.status] || "가져올 수 없는 화면입니다.", "err"); return; }
  show("검토 프로그램으로 보내는 중...");
  let resp, body;
  try {
    resp = await fetch(APP + "/capture", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Capture-Token": token },
      body: JSON.stringify(data),
    });
    body = await resp.json();
  } catch (e) {
    show("검토 프로그램에 연결하지 못했습니다. purchasing_start.bat 이 켜져 있는지 확인하세요.", "err");
    return;
  }
  if (!resp.ok || !body.ok) { show(body.error || ("오류 " + resp.status), "err"); return; }
  reviewUrl = body.review_url;
  const lines = [
    "가져왔습니다: " + data.title.slice(0, 40),
    "선택 옵션: " + (data.selected_options.join(" / ") || "없음"),
    "가격 표시: " + (body.price_found ? "찾음" : "못 찾음 (검토 화면에서 입력)"),
    "이미지: " + body.images + "개",
  ].concat(data.notes || []);
  show(lines.join("\n"), "ok");
  $("open").hidden = false;
});

loadToken();
