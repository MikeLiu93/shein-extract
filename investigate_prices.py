import requests, json, threading, websocket, time

PRODUCT_URL = "https://us.shein.com/Armless-Sofa-Bed-Cover-Folding-Sofa-Cover-Futon-Velvet-Stretch-Couch-Slipcover-Velvet-Armless-Sofa-Bed-Cover-Stretch-Folding-Slipcover-For-Living-Roon-p-41479813.html?main_attr=27_2486"

def cdp_once(ws_url, method, params=None, timeout=30):
    result = {}
    done = threading.Event()
    def on_open(ws):
        ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
    def on_message(ws, msg):
        d = json.loads(msg)
        if d.get("id") == 1:
            result["data"] = d.get("result", {})
            done.set()
            ws.close()
    def on_error(ws, err):
        result["error"] = str(err)
        done.set()
    ws_app = websocket.WebSocketApp(ws_url, on_open=on_open, on_message=on_message, on_error=on_error)
    threading.Thread(target=ws_app.run_forever, daemon=True).start()
    done.wait(timeout=timeout)
    return result.get("data", {})

# Step 1: Create new tab
print("Creating new tab...")
resp = requests.put("http://localhost:9222/json/new")
tab = resp.json()
ws_url = tab["webSocketDebuggerUrl"]
print(f"Tab ID: {tab['id']}")
print(f"WS URL: {ws_url}")

# Step 2: Navigate to the product page
print(f"\nNavigating to product URL...")
nav_result = cdp_once(ws_url, "Page.navigate", {"url": PRODUCT_URL})
print(f"Navigation result: {nav_result}")

# Step 3: Wait for page to load
print("\nWaiting 8 seconds for page load...")
time.sleep(8)

# Step 4: Extract inline script data - search for sku_list, skuList, sale_attr, salePrice
print("\n=== Searching inline scripts for SKU/price data ===\n")

JS_EXTRACT = r"""
(function() {
    var scripts = document.querySelectorAll('script:not([src])');
    var results = [];
    var keywords = ['sku_list', 'skuList', 'sale_attr', 'salePrice', 'sku_info', 'skuInfo',
                     'productIntroData', 'goodsDetailV3', 'product_detail',
                     'mallPrice', 'retailPrice', 'saleDiscount', 'mall_price', 'retail_price',
                     'attrValueList', 'attr_value_list', 'skc_sale_attr', 'sku_code'];

    for (var i = 0; i < scripts.length; i++) {
        var text = scripts[i].textContent || '';
        if (text.length < 50) continue;

        var found = [];
        for (var k = 0; k < keywords.length; k++) {
            if (text.indexOf(keywords[k]) !== -1) {
                found.push(keywords[k]);
            }
        }

        if (found.length > 0) {
            results.push({
                scriptIndex: i,
                scriptLength: text.length,
                keywordsFound: found,
                snippet: text.substring(0, 300)
            });
        }
    }
    return JSON.stringify(results, null, 2);
})()
"""

r1 = cdp_once(ws_url, "Runtime.evaluate", {"expression": JS_EXTRACT, "returnByValue": True})
print("Scripts with price-related keywords:")
val = r1.get("result", {}).get("value", "[]")
try:
    parsed = json.loads(val)
    print(json.dumps(parsed, indent=2))
except:
    print(val)

# Step 5: Try to find productIntroData or similar global variable
print("\n=== Checking global JS variables ===\n")

JS_GLOBALS = r"""
(function() {
    var checks = [
        'window.gbProductIntroData',
        'window.__INITIAL_DATA__',
        'window.__INITIAL_STATE__',
        'window.gbRawData',
        'window.gbGoodsDetailInfo',
        'window.goodsDetailV3',
        'window.__raw_data__',
        'window.gbProductInfo'
    ];
    var found = {};
    for (var i = 0; i < checks.length; i++) {
        try {
            var val = eval(checks[i]);
            if (val !== undefined && val !== null) {
                found[checks[i]] = typeof val === 'object' ? Object.keys(val).slice(0, 30) : typeof val;
            }
        } catch(e) {}
    }
    return JSON.stringify(found, null, 2);
})()
"""

r2 = cdp_once(ws_url, "Runtime.evaluate", {"expression": JS_GLOBALS, "returnByValue": True})
val2 = r2.get("result", {}).get("value", "{}")
print("Global variables found:")
print(val2)

# Step 6: Deep dive - extract the actual sku_list data
print("\n=== Extracting actual SKU list data ===\n")

JS_SKU_EXTRACT = r"""
(function() {
    // Try multiple paths to find sku data
    var scripts = document.querySelectorAll('script:not([src])');
    for (var i = 0; i < scripts.length; i++) {
        var text = scripts[i].textContent || '';

        // Look for productIntroData or similar JSON blob
        var patterns = [
            /productIntroData\s*[:=]\s*(\{[\s\S]*?\})\s*[,;]/,
            /"sku_list"\s*:\s*(\[[\s\S]*?\])\s*,\s*"/,
            /"skuList"\s*:\s*(\[[\s\S]*?\])\s*,\s*"/
        ];

        // Instead of regex, try to find sku_list by position
        var skuIdx = text.indexOf('"sku_list"');
        if (skuIdx === -1) skuIdx = text.indexOf('"skuList"');
        if (skuIdx === -1) skuIdx = text.indexOf("'sku_list'");

        if (skuIdx !== -1) {
            // Get surrounding context
            var start = Math.max(0, skuIdx - 100);
            var end = Math.min(text.length, skuIdx + 3000);
            return JSON.stringify({
                scriptIndex: i,
                scriptLength: text.length,
                skuListPosition: skuIdx,
                context: text.substring(start, end)
            });
        }
    }
    return JSON.stringify({error: "sku_list not found in inline scripts"});
})()
"""

r3 = cdp_once(ws_url, "Runtime.evaluate", {"expression": JS_SKU_EXTRACT, "returnByValue": True})
val3 = r3.get("result", {}).get("value", "{}")
print("SKU list extraction:")
try:
    parsed3 = json.loads(val3)
    if "context" in parsed3:
        print(f"Script index: {parsed3['scriptIndex']}, length: {parsed3['scriptLength']}, position: {parsed3['skuListPosition']}")
        print(f"Context around sku_list:\n{parsed3['context'][:2000]}")
    else:
        print(json.dumps(parsed3, indent=2))
except:
    print(val3)

print("\n=== Done with initial investigation ===")
