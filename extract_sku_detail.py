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

# Get the existing tab
resp = requests.get("http://localhost:9222/json")
tabs = resp.json()
# Find the shein tab
ws_url = None
for t in tabs:
    if "shein.com" in t.get("url", ""):
        ws_url = t["webSocketDebuggerUrl"]
        print(f"Using tab: {t['url'][:80]}")
        break

if not ws_url:
    print("No shein tab found!")
    exit(1)

# Extract sku_list fully
print("\n=== EXTRACTING sku_list ===\n")
JS1 = r"""
(function() {
    try {
        var raw = window.gbRawData;
        // Navigate to find sku_list - it's in the product detail module
        var modules = raw.modules || {};
        var keys = Object.keys(modules);

        // Search through modules for sku_list
        for (var k = 0; k < keys.length; k++) {
            var mod = modules[keys[k]];
            if (mod && typeof mod === 'object') {
                var modStr = JSON.stringify(mod);
                if (modStr.indexOf('sku_list') !== -1) {
                    // Found it - now extract just the relevant part
                    return JSON.stringify({
                        moduleKey: keys[k],
                        moduleTopKeys: Object.keys(mod)
                    });
                }
            }
        }
        return JSON.stringify({error: "not found in modules", moduleKeys: keys});
    } catch(e) {
        return JSON.stringify({error: e.message});
    }
})()
"""
r1 = cdp_once(ws_url, "Runtime.evaluate", {"expression": JS1, "returnByValue": True})
val1 = r1.get("result", {}).get("value", "{}")
print("Module structure:", val1)

# Now extract sku_list directly
print("\n=== EXTRACTING sku_list entries ===\n")
JS2 = r"""
(function() {
    try {
        var raw = window.gbRawData;
        var modules = raw.modules || {};
        var keys = Object.keys(modules);

        for (var k = 0; k < keys.length; k++) {
            var mod = modules[keys[k]];
            if (!mod || typeof mod !== 'object') continue;

            // Recursive search for sku_list
            function findKey(obj, target, depth) {
                if (depth > 8) return null;
                if (obj[target]) return obj[target];
                var okeys = Object.keys(obj);
                for (var i = 0; i < okeys.length; i++) {
                    if (typeof obj[okeys[i]] === 'object' && obj[okeys[i]] !== null) {
                        var found = findKey(obj[okeys[i]], target, depth + 1);
                        if (found) return found;
                    }
                }
                return null;
            }

            var skuList = findKey(mod, 'sku_list', 0);
            if (skuList && Array.isArray(skuList)) {
                return JSON.stringify({
                    moduleKey: keys[k],
                    skuCount: skuList.length,
                    firstSku: skuList[0],
                    allSkus: skuList
                }, null, 2);
            }
        }
        return JSON.stringify({error: "sku_list array not found"});
    } catch(e) {
        return JSON.stringify({error: e.message, stack: e.stack});
    }
})()
"""
r2 = cdp_once(ws_url, "Runtime.evaluate", {"expression": JS2, "returnByValue": True})
val2 = r2.get("result", {}).get("value", "{}")
try:
    parsed = json.loads(val2)
    print(json.dumps(parsed, indent=2)[:8000])
except:
    print(val2[:5000])

# Extract sale_attr structure
print("\n=== EXTRACTING sale_attr / saleAttr ===\n")
JS3 = r"""
(function() {
    try {
        var raw = window.gbRawData;
        var modules = raw.modules || {};
        var keys = Object.keys(modules);

        for (var k = 0; k < keys.length; k++) {
            var mod = modules[keys[k]];
            if (!mod || typeof mod !== 'object') continue;

            function findKey(obj, target, depth) {
                if (depth > 8) return null;
                if (obj[target]) return obj[target];
                var okeys = Object.keys(obj);
                for (var i = 0; i < okeys.length; i++) {
                    if (typeof obj[okeys[i]] === 'object' && obj[okeys[i]] !== null) {
                        var found = findKey(obj[okeys[i]], target, depth + 1);
                        if (found) return found;
                    }
                }
                return null;
            }

            var saleAttr = findKey(mod, 'sale_attr', 0);
            if (saleAttr) {
                // Also get skc_sale_attr
                var skcSaleAttr = findKey(mod, 'skc_sale_attr', 0);
                return JSON.stringify({
                    moduleKey: keys[k],
                    sale_attr: saleAttr,
                    skc_sale_attr: skcSaleAttr
                }, null, 2);
            }
        }
        return JSON.stringify({error: "sale_attr not found"});
    } catch(e) {
        return JSON.stringify({error: e.message});
    }
})()
"""
r3 = cdp_once(ws_url, "Runtime.evaluate", {"expression": JS3, "returnByValue": True})
val3 = r3.get("result", {}).get("value", "{}")
try:
    parsed3 = json.loads(val3)
    print(json.dumps(parsed3, indent=2)[:8000])
except:
    print(val3[:5000])

# Also look for the parent object structure that contains sku_list
print("\n=== PARENT OBJECT KEYS around sku_list ===\n")
JS4 = r"""
(function() {
    try {
        var raw = window.gbRawData;
        var modules = raw.modules || {};
        var keys = Object.keys(modules);

        for (var k = 0; k < keys.length; k++) {
            var mod = modules[keys[k]];
            if (!mod || typeof mod !== 'object') continue;

            function findParent(obj, target, depth) {
                if (depth > 8) return null;
                if (obj[target] !== undefined) return obj;
                var okeys = Object.keys(obj);
                for (var i = 0; i < okeys.length; i++) {
                    if (typeof obj[okeys[i]] === 'object' && obj[okeys[i]] !== null) {
                        var found = findParent(obj[okeys[i]], target, depth + 1);
                        if (found) return found;
                    }
                }
                return null;
            }

            var parent = findParent(mod, 'sku_list', 0);
            if (parent) {
                var parentKeys = Object.keys(parent);
                // Get shallow summary of each key
                var summary = {};
                for (var i = 0; i < parentKeys.length; i++) {
                    var val = parent[parentKeys[i]];
                    if (val === null) summary[parentKeys[i]] = null;
                    else if (Array.isArray(val)) summary[parentKeys[i]] = "Array(" + val.length + ")";
                    else if (typeof val === 'object') summary[parentKeys[i]] = "Object(" + Object.keys(val).length + " keys: " + Object.keys(val).slice(0, 5).join(", ") + ")";
                    else summary[parentKeys[i]] = val;
                }
                return JSON.stringify(summary, null, 2);
            }
        }
        return JSON.stringify({error: "parent not found"});
    } catch(e) {
        return JSON.stringify({error: e.message});
    }
})()
"""
r4 = cdp_once(ws_url, "Runtime.evaluate", {"expression": JS4, "returnByValue": True})
val4 = r4.get("result", {}).get("value", "{}")
try:
    parsed4 = json.loads(val4)
    print(json.dumps(parsed4, indent=2))
except:
    print(val4[:3000])
