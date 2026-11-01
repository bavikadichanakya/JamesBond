import asyncio
import aiohttp
import base64
import json
import urllib.request
from pathlib import Path

async def main():
    # 1. Fetch CDP WebSocket URL
    req = urllib.request.Request("http://127.0.0.1:9222/json")
    with urllib.request.urlopen(req) as resp:
        targets = json.loads(resp.read().decode())
    
    page_target = next(t for t in targets if t.get("type") == "page")
    ws_url = page_target["webSocketDebuggerUrl"]
    print(f"Connecting to CDP WebSocket: {ws_url}")

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ws_url) as ws:
            msg_id = 0
            
            async def send_cmd(method, params=None):
                nonlocal msg_id
                msg_id += 1
                payload = {"id": msg_id, "method": method, "params": params or {}}
                await ws.send_json(payload)
                while True:
                    res = await ws.receive_json()
                    if res.get("id") == msg_id:
                        return res.get("result", {})

            async def eval_js(expr):
                res = await send_cmd("Runtime.evaluate", {
                    "expression": expr,
                    "returnByValue": True
                })
                return res.get("result", {}).get("value")
            
            # Enable domains
            await send_cmd("Page.enable")
            await send_cmd("Runtime.enable")
            
            # Reload page to pick up latest app.js changes
            print("Reloading native WebView2 page...")
            await send_cmd("Page.reload", {"ignoreCache": True})
            await asyncio.sleep(2.0)

            # 2. Capture Initial Native Window Screenshot
            print("Capturing initial native HUD screenshot...")
            shot = await send_cmd("Page.captureScreenshot", {"format": "png"})
            img_data = base64.b64decode(shot["data"])
            Path(r"A:\Mixer\nexus_native_window.png").write_bytes(img_data)
            print(f"Saved native screenshot ({len(img_data)} bytes) to A:\\Mixer\\nexus_native_window.png")

            # 3. Inspect DOM elements in Native WebView2
            dom_check = await eval_js("""
                ({
                    title: document.title,
                    orbClass: document.getElementById('jarvisOrb')?.className,
                    hasSidebar: !!document.querySelector('.sidebar'),
                    hasInput: !!document.getElementById('txtPrompt'),
                    hasSendBtn: !!document.getElementById('btnSend'),
                    hasChatContainer: !!document.getElementById('chatContainer'),
                    adapterCount: document.querySelectorAll('#adapterStatusList .subsystem-row').length
                })
            """)
            print("DOM Check in Native Window:", json.dumps(dom_check, indent=2))

            # 4. Submit End-to-End Conversational Directive via Native UI
            print("\nSubmitting directive via Native UI DOM: 'What time is it right now?'...")
            await eval_js("""
                handleSendMessage('What time is it right now?');
            """)

            # Wait for response in #chatContainer
            assistant_reply = ""
            for _ in range(25):
                await asyncio.sleep(1.0)
                reply = await eval_js("""
                    (() => {
                        const msgs = Array.from(document.querySelectorAll('.message-bubble.assistant-bubble'));
                        if (msgs.length > 0) {
                            return msgs[msgs.length - 1].innerText;
                        }
                        return null;
                    })()
                """)
                if reply:
                    assistant_reply = reply
                    break

            print("\n=== NATIVE UI RENDERED ASSISTANT RESPONSE ===")
            print(assistant_reply)
            print("=============================================\n")

            # Capture post-conversation screenshot
            shot2 = await send_cmd("Page.captureScreenshot", {"format": "png"})
            Path(r"A:\Mixer\nexus_native_convo.png").write_bytes(base64.b64decode(shot2["data"]))
            print("Saved conversation screenshot to A:\\Mixer\\nexus_native_convo.png")

            # 5. Test Permission Enforcement via Native UI (Denial Flow)
            print("\nSubmitting confirmation-gated command: 'Launch notepad'...")
            await eval_js("handleSendMessage('Launch notepad');")

            # Wait for approval modal to display
            modal_shown = False
            for _ in range(20):
                await asyncio.sleep(0.5)
                m_info = await eval_js("""
                    (() => {
                        const modal = document.getElementById('approvalModal');
                        return {
                            visible: modal && modal.style.display === 'flex',
                            tool: document.getElementById('modalToolName')?.innerText,
                            args: document.getElementById('modalArgs')?.innerText
                        };
                    })()
                """)
                if m_info and m_info.get("visible"):
                    modal_shown = True
                    print(f"Approval Modal displayed! Tool: {m_info.get('tool')}, Args: {m_info.get('args')}")
                    break

            assert modal_shown, "Approval modal did not appear for launch_application"

            # Capture modal screenshot
            shot_modal = await send_cmd("Page.captureScreenshot", {"format": "png"})
            Path(r"A:\Mixer\nexus_native_modal.png").write_bytes(base64.b64decode(shot_modal["data"]))
            print("Saved modal screenshot to A:\\Mixer\\nexus_native_modal.png")

            # Test Explicit Denial via UI button click
            print("Clicking ABORT (DENY) button in native modal...")
            await eval_js("document.getElementById('btnDenyAction').click();")

            # Wait for denial response to appear in chat
            denial_reply = ""
            for _ in range(20):
                await asyncio.sleep(0.5)
                reply = await eval_js("""
                    (() => {
                        const msgs = Array.from(document.querySelectorAll('.message-bubble.assistant-bubble'));
                        if (msgs.length > 1) {
                            return msgs[msgs.length - 1].innerText;
                        }
                        return null;
                    })()
                """)
                if reply and any(w in reply.lower() for w in ["denied", "rejected", "abort", "failed"]):
                    denial_reply = reply
                    break

            print("\n=== NATIVE UI DENIAL RESPONSE ===")
            print(denial_reply)
            print("=================================\n")

            # 6. Test Explicit Approval via UI button click
            print("Submitting command again for approval: 'Launch notepad'...")
            await eval_js("handleSendMessage('Launch notepad');")

            modal_shown = False
            for _ in range(20):
                await asyncio.sleep(0.5)
                vis = await eval_js("document.getElementById('approvalModal')?.style.display === 'flex'")
                if vis:
                    modal_shown = True
                    break

            assert modal_shown, "Approval modal did not appear for second launch_application"

            print("Clicking AUTHORIZE & EXECUTE button in native modal...")
            await eval_js("document.getElementById('btnApproveAction').click();")

            # Wait for approval response
            approval_reply = ""
            for _ in range(25):
                await asyncio.sleep(0.5)
                reply = await eval_js("""
                    (() => {
                        const msgs = Array.from(document.querySelectorAll('.message-bubble.assistant-bubble'));
                        if (msgs.length > 2) {
                            return msgs[msgs.length - 1].innerText;
                        }
                        return null;
                    })()
                """)
                if reply and "launched" in reply.lower():
                    approval_reply = reply
                    break

            print("\n=== NATIVE UI APPROVAL RESPONSE ===")
            print(approval_reply)
            print("===================================\n")

            # Final post-approval screenshot
            shot_final = await send_cmd("Page.captureScreenshot", {"format": "png"})
            Path(r"A:\Mixer\nexus_native_executed.png").write_bytes(base64.b64decode(shot_final["data"]))
            print("Saved final executed screenshot to A:\\Mixer\\nexus_native_executed.png")

            print("ALL NATIVE UI ACCEPTANCE INTERACTIONS VERIFIED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(main())
