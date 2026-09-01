import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";

import { chromium } from "@playwright/test";


class DriverFailure extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
}


const fail = (code) => {
  throw new DriverFailure(code);
};


const sha256 = (value) =>
  createHash("sha256").update(value, "utf8").digest("hex");


const truncateUtf8 = (value, maxBytes) => {
  let result = "";
  let bytes = 0;
  for (const character of value) {
    const size = Buffer.byteLength(character, "utf8");
    if (bytes + size > maxBytes) {
      break;
    }
    result += character;
    bytes += size;
  }
  return result;
};


const assertRequest = (request) => {
  if (
    request === null ||
    typeof request !== "object" ||
    request.schema_version !== 1 ||
    request.fixture === null ||
    typeof request.fixture !== "object" ||
    typeof request.fixture.origin !== "string" ||
    request.fixture.documents === null ||
    typeof request.fixture.documents !== "object" ||
    request.fixture.redirects === null ||
    typeof request.fixture.redirects !== "object" ||
    !Array.isArray(request.actions) ||
    request.limits === null ||
    typeof request.limits !== "object"
  ) {
    fail("browser_driver_invalid_response");
  }
  const { action_timeout_ms: actionTimeoutMs, max_screenshot_bytes: maxScreenshotBytes, max_text_bytes: maxTextBytes } = request.limits;
  if (
    !Number.isInteger(actionTimeoutMs) ||
    actionTimeoutMs < 1 ||
    actionTimeoutMs > 60_000 ||
    !Number.isInteger(maxScreenshotBytes) ||
    maxScreenshotBytes < 1 ||
    maxScreenshotBytes > 2 * 1024 * 1024 ||
    !Number.isInteger(maxTextBytes) ||
    maxTextBytes < 1 ||
    maxTextBytes > 64 * 1024
  ) {
    fail("browser_driver_invalid_response");
  }
};


const locatorFor = (page, elementId) =>
  page.locator(`[data-agent-id=${JSON.stringify(elementId)}]`);


const requireElement = async (page, elementId) => {
  const locator = locatorFor(page, elementId);
  const count = await locator.count();
  if (count === 0 || !(await locator.first().isVisible())) {
    fail("browser_element_missing");
  }
  if (count !== 1) {
    fail("browser_element_ambiguous");
  }
  return locator;
};


const pageState = async (page) => {
  const state = await page.evaluate(() => {
    const normalize = (value) => value.replace(/\s+/g, " ").trim();
    const elements = Array.from(document.querySelectorAll("[data-agent-id]"))
      .map((element) => ({
        id: element.getAttribute("data-agent-id") ?? "",
        tag: element.tagName.toLowerCase(),
        text: normalize(element.textContent ?? ""),
        type: element.getAttribute("type") ?? "",
      }))
      .sort((left, right) => left.id.localeCompare(right.id));
    return {
      title: document.title,
      path: `${window.location.pathname}${window.location.search}`,
      elements,
    };
  });
  return {
    ...state,
    digest: sha256(JSON.stringify(state)),
  };
};


const currentOrigin = (page) => {
  try {
    return new URL(page.url()).origin;
  } catch {
    fail("browser_page_mismatch");
  }
};


const run = async (request) => {
  assertRequest(request);
  const fixtureOrigin = new URL(request.fixture.origin).origin;
  if (fixtureOrigin !== request.fixture.origin) {
    fail("browser_driver_invalid_response");
  }
  const documents = new Map(Object.entries(request.fixture.documents));
  const redirects = new Map(Object.entries(request.fixture.redirects));
  const { action_timeout_ms: actionTimeoutMs, max_screenshot_bytes: maxScreenshotBytes, max_text_bytes: maxTextBytes } = request.limits;

  let browser;
  try {
    browser = await chromium.launch({ headless: true });
  } catch {
    fail("browser_driver_unavailable");
  }
  const context = await browser.newContext({
    acceptDownloads: false,
    serviceWorkers: "block",
    viewport: { width: 1280, height: 720 },
  });
  context.setDefaultTimeout(actionTimeoutMs);
  context.setDefaultNavigationTimeout(actionTimeoutMs);

  let blockedCode = null;
  await context.route("**/*", async (route) => {
    const requestUrl = route.request().url();
    let parsed;
    try {
      parsed = new URL(requestUrl);
    } catch {
      blockedCode = "browser_cross_origin";
      await route.abort("blockedbyclient");
      return;
    }
    if (parsed.origin !== fixtureOrigin) {
      blockedCode = "browser_cross_origin";
      await route.abort("blockedbyclient");
      return;
    }
    if (route.request().resourceType() !== "document") {
      blockedCode = "browser_fixture_not_found";
      await route.abort("blockedbyclient");
      return;
    }
    const redirectTarget = redirects.get(requestUrl);
    if (redirectTarget !== undefined) {
      blockedCode = "browser_redirect_unplanned";
      await route.abort("blockedbyclient");
      return;
    }
    const document = documents.get(requestUrl);
    if (document === undefined) {
      blockedCode = "browser_fixture_not_found";
      await route.abort("blockedbyclient");
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "text/html; charset=utf-8",
      headers: {
        "cache-control": "no-store",
        "content-security-policy": "default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; form-action 'self'",
      },
      body: document,
    });
  });

  const page = await context.newPage();
  let eventFailureCode = null;
  page.on("popup", async (popup) => {
    eventFailureCode = "browser_popup_blocked";
    await popup.close().catch(() => undefined);
  });
  page.on("download", async (download) => {
    eventFailureCode = "browser_download_blocked";
    await download.cancel().catch(() => undefined);
  });
  page.on("filechooser", () => {
    eventFailureCode = "browser_upload_blocked";
  });

  const results = [];
  try {
    for (const action of request.actions) {
      if (
        action === null ||
        typeof action !== "object" ||
        typeof action.id !== "string" ||
        typeof action.kind !== "string" ||
        action.origin !== fixtureOrigin
      ) {
        fail("browser_driver_invalid_response");
      }
      blockedCode = null;
      eventFailureCode = null;
      let text = null;

      try {
        if (action.kind === "navigate") {
          if (
            typeof action.url !== "string" ||
            (!documents.has(action.url) && !redirects.has(action.url)) ||
            typeof action.navigation_url !== "string" ||
            !documents.has(action.navigation_url)
          ) {
            fail("browser_fixture_not_found");
          }
          await page.goto(action.navigation_url, { waitUntil: "domcontentloaded" });
        } else {
          if (currentOrigin(page) !== fixtureOrigin) {
            fail("browser_page_mismatch");
          }
          if (typeof action.page_url !== "string" || page.url() !== action.page_url) {
            fail("browser_page_mismatch");
          }
          if (typeof action.element_id !== "string") {
            fail("browser_driver_invalid_response");
          }
          const locator = await requireElement(page, action.element_id);
          const before = await pageState(page);
          if (
            typeof action.expected_page_digest !== "string" ||
            action.expected_page_digest !== before.digest
          ) {
            fail("browser_page_changed");
          }
          if (action.kind === "read_text") {
            text = truncateUtf8(await locator.innerText(), maxTextBytes);
          } else if (action.kind === "click") {
            await locator.click();
          } else if (action.kind === "type") {
            if (typeof action.value !== "string") {
              fail("browser_driver_invalid_response");
            }
            await locator.fill(action.value);
          } else if (action.kind === "submit") {
            await locator.evaluate((element) => {
              if (!(element instanceof HTMLFormElement)) {
                throw new Error("not a form");
              }
              element.requestSubmit();
            });
          } else {
            fail("browser_driver_invalid_response");
          }
        }
      } catch (error) {
        if (error instanceof DriverFailure) {
          throw error;
        }
        if (blockedCode !== null) {
          fail(blockedCode);
        }
        if (eventFailureCode !== null) {
          fail(eventFailureCode);
        }
        if (error?.name === "TimeoutError") {
          fail("browser_action_timeout");
        }
        if (action.kind === "submit") {
          fail("browser_element_missing");
        }
        fail("browser_driver_invalid_response");
      }

      await page.waitForTimeout(25);
      if (blockedCode !== null) {
        fail(blockedCode);
      }
      if (eventFailureCode !== null) {
        fail(eventFailureCode);
      }
      if (currentOrigin(page) !== fixtureOrigin) {
        fail("browser_cross_origin");
      }
      if (action.kind !== "navigate" && page.url() !== action.page_url) {
        fail("browser_page_mismatch");
      }
      const after = await pageState(page);
      results.push({
        action_id: action.id,
        kind: action.kind,
        origin: fixtureOrigin,
        page_digest: after.digest,
        text,
      });
    }

    const state = await pageState(page);
    const visibleElementIds = await page.locator("[data-agent-id]").evaluateAll((elements) =>
      elements
        .filter((element) => {
          const style = window.getComputedStyle(element);
          const bounds = element.getBoundingClientRect();
          return style.visibility !== "hidden" && style.display !== "none" && bounds.width > 0 && bounds.height > 0;
        })
        .map((element) => element.getAttribute("data-agent-id") ?? "")
        .sort(),
    );
    const screenshot = await page.screenshot({
      animations: "disabled",
      type: "png",
    });
    if (screenshot.byteLength > maxScreenshotBytes) {
      fail("browser_screenshot_too_large");
    }
    return {
      ok: true,
      actions: results,
      observation: {
        origin: fixtureOrigin,
        page_digest: state.digest,
        visible_element_ids: visibleElementIds,
        url: page.url(),
        title: truncateUtf8(await page.title(), maxTextBytes),
        text: truncateUtf8(await page.locator("body").innerText(), maxTextBytes),
        screenshot_base64: screenshot.toString("base64"),
      },
    };
  } finally {
    await context.close().catch(() => undefined);
    await browser.close().catch(() => undefined);
  }
};


const main = async () => {
  const [, , requestPath, responsePath] = process.argv;
  if (typeof requestPath !== "string" || typeof responsePath !== "string") {
    process.exitCode = 1;
    return;
  }
  let response;
  try {
    const request = JSON.parse(await readFile(requestPath, "utf8"));
    response = await run(request);
  } catch (error) {
    response = {
      ok: false,
      code: error instanceof DriverFailure ? error.code : "browser_driver_invalid_response",
    };
    process.exitCode = 1;
  }
  await writeFile(responsePath, JSON.stringify(response), {
    encoding: "utf8",
    flag: "wx",
    mode: 0o600,
  });
};


await main();
