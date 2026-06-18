import json

import streamlit.components.v1 as components


def render_share_to_mail(
    subject: str,
    body: str,
    attachments: list[dict],
    height: int = 120,
) -> None:
    """
    Mobile-friendly share sheet: opens Gmail/mail app with text + file attachments.
    attachments: list of {name, data (bytes), mime}
    """
    import base64

    files_json = json.dumps(
        [
            {
                "name": a["name"],
                "b64": base64.b64encode(a["data"]).decode(),
                "type": a["mime"],
            }
            for a in attachments
        ]
    )

    html = f"""
    <!DOCTYPE html>
    <html>
    <body style="margin:0;font-family:sans-serif;">
      <button id="shareBtn" style="
        width:100%;padding:12px 20px;background:#1a73e8;color:white;
        border:none;border-radius:8px;font-size:16px;font-weight:500;cursor:pointer;">
        📱 Share to Mail App (with attachments)
      </button>
      <p id="status" style="margin:8px 0 0;font-size:13px;color:#555;"></p>
      <script>
        const filesData = {files_json};
        const subject = {json.dumps(subject)};
        const body = {json.dumps(body)};

        function b64ToFile(item) {{
          const bin = atob(item.b64);
          const arr = new Uint8Array(bin.length);
          for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
          return new File([arr], item.name, {{ type: item.type }});
        }}

        document.getElementById("shareBtn").onclick = async () => {{
          const status = document.getElementById("status");
          try {{
            const files = filesData.map(b64ToFile);
            const shareData = {{ title: subject, text: body }};
            if (files.length) shareData.files = files;

            if (!navigator.share) {{
              status.textContent = "Web Share not supported on this browser — use Download .eml below.";
              return;
            }}
            if (files.length && navigator.canShare && !navigator.canShare(shareData)) {{
              status.textContent = "This browser cannot share files — use Download .eml below.";
              return;
            }}
            await navigator.share(shareData);
            status.textContent = "Opened share sheet — pick Gmail or your mail app.";
          }} catch (err) {{
            if (err.name !== "AbortError") {{
              status.textContent = "Share failed: " + err.message;
            }}
          }}
        }};
      </script>
    </body>
    </html>
    """
    components.html(html, height=height)
