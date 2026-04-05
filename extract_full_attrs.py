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

# Get the shein tab
resp = requests.get("http://localhost:9222/json")
tabs = resp.json()
ws_url = None
for t in tabs:
    if "shein.com" in t.get("url", ""):
        ws_url = t["webSocketDebuggerUrl"]
        break

# 1. Get the full saleAttr module structure
print("=== saleAttr module: mainSaleAttribute ===\n")
JS1 = r"""
(function() {
    var mod = window.gbRawData.modules.saleAttr;
    return JSON.stringify({
        topKeys: Object.keys(mod),
        mainSaleAttribute: mod.mainSaleAttribute,
        multiLevelSaleAttribute: mod.multiLevelSaleAttribute
    }, null, 2);
})()
"""
r1 = cdp_once(ws_url, "Runtime.evaluate", {"expression": JS1, "returnByValue": True})
val = r1.get("result", {}).get("value", "{}")
try:
    p = json.loads(val)
    print(json.dumps(p, indent=2)[:6000])
except:
    print(val[:5000])

# 2. Get sizeInfo
print("\n=== saleAttr module: sizeInfo ===\n")
JS2 = r"""
(function() {
    var mod = window.gbRawData.modules.saleAttr;
    return JSON.stringify(mod.sizeInfo, null, 2);
})()
"""
r2 = cdp_once(ws_url, "Runtime.evaluate", {"expression": JS2, "returnByValue": True})
val2 = r2.get("result", {}).get("value", "{}")
try:
    p2 = json.loads(val2)
    print(json.dumps(p2, indent=2)[:4000])
except:
    print(val2[:4000])

# 3. Get ALL sku_list entries across all color variants (look in all productIntro data)
print("\n=== Looking for ALL sku entries across color variants ===\n")
JS3 = r"""
(function() {
    // Search entire gbRawData for all sku_list arrays
    var results = [];
    function findAllSkuLists(obj, path, depth) {
        if (depth > 10 || !obj || typeof obj !== 'object') return;
        if (obj.sku_list && Array.isArray(obj.sku_list)) {
            var skus = obj.sku_list.map(function(s) {
                return {
                    sku_code: s.sku_code,
                    stock: s.stock,
                    salePrice: s.priceInfo && s.priceInfo.salePrice,
                    retailPrice: s.priceInfo && s.priceInfo.retailPrice,
                    unitDiscount: s.priceInfo && s.priceInfo.unitDiscount,
                    // Also check s.price
                    price_salePrice: s.price && s.price.salePrice,
                    price_retailPrice: s.price && s.price.retailPrice,
                    price_unit_discount: s.price && s.price.unit_discount
                };
            });
            results.push({path: path, skuCount: obj.sku_list.length, skus: skus, goods_id: obj.goods_id, skc_name: obj.skc_name});
        }
        var keys = Object.keys(obj);
        for (var i = 0; i < keys.length; i++) {
            if (typeof obj[keys[i]] === 'object') {
                findAllSkuLists(obj[keys[i]], path + '.' + keys[i], depth + 1);
            }
        }
    }
    findAllSkuLists(window.gbRawData, 'gbRawData', 0);
    return JSON.stringify(results, null, 2);
})()
"""
r3 = cdp_once(ws_url, "Runtime.evaluate", {"expression": JS3, "returnByValue": True})
val3 = r3.get("result", {}).get("value", "[]")
try:
    p3 = json.loads(val3)
    print(json.dumps(p3, indent=2)[:6000])
except:
    print(val3[:5000])

# 4. Look at productIntro module / productDetails module
print("\n=== All module keys in gbRawData ===\n")
JS4 = r"""
(function() {
    var mods = window.gbRawData.modules;
    var summary = {};
    var keys = Object.keys(mods);
    for (var i = 0; i < keys.length; i++) {
        var m = mods[keys[i]];
        if (m && typeof m === 'object') {
            summary[keys[i]] = Object.keys(m).slice(0, 15);
        } else {
            summary[keys[i]] = typeof m;
        }
    }
    return JSON.stringify(summary, null, 2);
})()
"""
r4 = cdp_once(ws_url, "Runtime.evaluate", {"expression": JS4, "returnByValue": True})
val4 = r4.get("result", {}).get("value", "{}")
try:
    p4 = json.loads(val4)
    print(json.dumps(p4, indent=2)[:5000])
except:
    print(val4[:5000])

# 5. Check productInfo module for price structures
print("\n=== productInfo module (if exists) ===\n")
JS5 = r"""
(function() {
    var mods = window.gbRawData.modules;
    // Look for productInfo or similar
    var candidates = ['productInfo', 'productIntro', 'productDetail', 'commonInfo'];
    var result = {};
    for (var c = 0; c < candidates.length; c++) {
        if (mods[candidates[c]]) {
            result[candidates[c]] = Object.keys(mods[candidates[c]]);
        }
    }
    return JSON.stringify(result, null, 2);
})()
"""
r5 = cdp_once(ws_url, "Runtime.evaluate", {"expression": JS5, "returnByValue": True})
val5 = r5.get("result", {}).get("value", "{}")
print(val5)

# 6. Check for related_color data structure which maps colors to different SKC groups
print("\n=== Looking for related color/variant groups with prices ===\n")
JS6 = r"""
(function() {
    var mods = window.gbRawData.modules;
    // Look at saleAttr.mainSaleAttribute structure for colors
    var main = mods.saleAttr.mainSaleAttribute;
    if (!main) return JSON.stringify({error: "no mainSaleAttribute"});

    // Each color attr_value has its own skc, check if it links to different sku_list groups
    // Also check the multiLevelSaleAttribute which shows size options per color
    var multi = mods.saleAttr.multiLevelSaleAttribute;

    // Look at the attr_value_list for sizes
    var attrSizeTips = mods.saleAttr.attr_size_tips;

    return JSON.stringify({
        mainSaleAttr_keys: main ? Object.keys(main) : null,
        multiLevel_sample: multi ? JSON.stringify(multi).substring(0, 2000) : null,
        attr_size_tips: attrSizeTips
    }, null, 2);
})()
"""
r6 = cdp_once(ws_url, "Runtime.evaluate", {"expression": JS6, "returnByValue": True})
val6 = r6.get("result", {}).get("value", "{}")
try:
    p6 = json.loads(val6)
    if p6.get("multiLevel_sample"):
        try:
            ml = json.loads(p6["multiLevel_sample"])
            p6["multiLevel_sample"] = ml
        except:
            pass
    print(json.dumps(p6, indent=2)[:6000])
except:
    print(val6[:5000])
