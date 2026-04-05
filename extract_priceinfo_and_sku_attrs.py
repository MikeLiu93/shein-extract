import requests, json, threading, websocket, time

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

resp = requests.get("http://localhost:9222/json")
tabs = resp.json()
ws_url = None
for t in tabs:
    if "shein.com" in t.get("url", ""):
        ws_url = t["webSocketDebuggerUrl"]
        break

# 1. Get top-level priceInfo module
print("=== priceInfo module (top-level) ===\n")
JS1 = r"""
(function() {
    var pi = window.gbRawData.modules.priceInfo;
    // Trim multiPaymentShowList for brevity
    var copy = JSON.parse(JSON.stringify(pi));
    if (copy.multiPaymentShowList) copy.multiPaymentShowList = "[" + copy.multiPaymentShowList.length + " items]";
    return JSON.stringify(copy, null, 2);
})()
"""
r1 = cdp_once(ws_url, "Runtime.evaluate", {"expression": JS1, "returnByValue": True})
val1 = r1.get("result", {}).get("value", "{}")
print(val1[:4000])

# 2. Get the full sku_list entry structure (all keys, including sale_attr if present on each SKU)
print("\n=== Full SKU entry keys and sale_attr ===\n")
JS2 = r"""
(function() {
    var skuList = window.gbRawData.modules.saleAttr.multiLevelSaleAttribute.sku_list;
    if (!skuList || !skuList.length) return JSON.stringify({error: "no sku_list"});

    var sku = skuList[0];
    // Get all top-level keys
    var topKeys = Object.keys(sku);

    // Check for sale_attr_list or sku_sale_attr
    var attrKeys = topKeys.filter(function(k) {
        return k.toLowerCase().indexOf('attr') !== -1 || k.toLowerCase().indexOf('size') !== -1;
    });

    return JSON.stringify({
        topLevelKeys: topKeys,
        attrRelatedKeys: attrKeys,
        fullSku: sku
    }, null, 2);
})()
"""
r2 = cdp_once(ws_url, "Runtime.evaluate", {"expression": JS2, "returnByValue": True})
val2 = r2.get("result", {}).get("value", "{}")
try:
    p2 = json.loads(val2)
    # Print just keys and the attr-related data
    print("Top-level keys:", p2.get("topLevelKeys"))
    print("Attr-related keys:", p2.get("attrRelatedKeys"))
    # Print full SKU but truncate multiPaymentShowList
    full = p2.get("fullSku", {})
    if full.get("priceInfo", {}).get("multiPaymentShowList"):
        full["priceInfo"]["multiPaymentShowList"] = f"[{len(full['priceInfo']['multiPaymentShowList'])} items]"
    if full.get("price", {}).get("promotion_discount_info"):
        full["price"]["promotion_discount_info"] = f"[{len(full['price']['promotion_discount_info'])} items]"
    print("\nFull SKU entry:")
    print(json.dumps(full, indent=2)[:5000])
except:
    print(val2[:5000])

# 3. Now navigate to a product with SIZE variants (clothing) to see multi-SKU structure
# Let's try a dress with multiple sizes
print("\n\n========================================")
print("=== NAVIGATING TO A PRODUCT WITH SIZES ===")
print("========================================\n")

SIZED_URL = "https://us.shein.com/SHEIN-EZwear-Solid-Oversized-Tee-p-10221065.html"
print(f"Navigating to: {SIZED_URL}")
nav = cdp_once(ws_url, "Page.navigate", {"url": SIZED_URL})
print(f"Nav result: {nav}")
time.sleep(8)

# 4. Extract sku_list from the sized product
print("\n=== SKU list from sized product ===\n")
JS4 = r"""
(function() {
    try {
        var multi = window.gbRawData.modules.saleAttr.multiLevelSaleAttribute;
        var skuList = multi.sku_list;
        if (!skuList) return JSON.stringify({error: "no sku_list", keys: Object.keys(multi)});

        var summary = skuList.map(function(s) {
            return {
                sku_code: s.sku_code,
                stock: s.stock,
                sale_attr: s.sku_sale_attr || s.sale_attr || s.saleAttr || null,
                sku_sale_attr: s.sku_sale_attr,
                attr_value_id: s.attr_value_id,
                salePrice: s.priceInfo ? s.priceInfo.salePrice : null,
                retailPrice: s.priceInfo ? s.priceInfo.retailPrice : null,
                unitDiscount: s.priceInfo ? s.priceInfo.unitDiscount : null,
                price_salePrice: s.price ? s.price.salePrice : null,
                allTopKeys: Object.keys(s)
            };
        });

        return JSON.stringify({
            goods_id: multi.goods_id,
            skuCount: skuList.length,
            skus: summary
        }, null, 2);
    } catch(e) {
        return JSON.stringify({error: e.message, stack: e.stack});
    }
})()
"""
r4 = cdp_once(ws_url, "Runtime.evaluate", {"expression": JS4, "returnByValue": True})
val4 = r4.get("result", {}).get("value", "{}")
try:
    p4 = json.loads(val4)
    print(json.dumps(p4, indent=2)[:8000])
except:
    print(val4[:8000])

# 5. Also check the comboStock / skuMap for this product
print("\n=== comboStock / skuMap for sized product ===\n")
JS5 = r"""
(function() {
    try {
        var multi = window.gbRawData.modules.saleAttr.multiLevelSaleAttribute;
        return JSON.stringify({
            comboStock: multi.comboStock,
            goods_id: multi.goods_id
        }, null, 2);
    } catch(e) {
        return JSON.stringify({error: e.message});
    }
})()
"""
r5 = cdp_once(ws_url, "Runtime.evaluate", {"expression": JS5, "returnByValue": True})
val5 = r5.get("result", {}).get("value", "{}")
try:
    p5 = json.loads(val5)
    print(json.dumps(p5, indent=2)[:4000])
except:
    print(val5[:4000])
