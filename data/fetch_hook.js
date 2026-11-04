(() => {

    if (window.__doubao_stream_hook_installed) {
        return;
    }

    window.__doubao_stream_hook_installed = true;

    const originalFetch = window.fetch;

    window.fetch = async function(...args) {

        let requestUrl = "";

        try {
            if (typeof args[0] === "string") {
                requestUrl = args[0];
            } else if (args[0] && typeof args[0].url === "string") {
                requestUrl = args[0].url;
            }
        } catch (e) {
        }

        const isCompletion = requestUrl.includes("/chat/completion");
        const response = await originalFetch.apply(this, args);

        if (!isCompletion) {
            return response;
        }

        console.log("[COMPLETION_RESPONSE]", "status=" + response.status);

        try {

            const clone = response.clone();

            if (!clone.body) {
                console.log("[COMPLETION_STREAM_END]", "chunks=0");
                return response;
            }

            const reader = clone.body.getReader();
            const decoder = new TextDecoder("utf-8");

            let chunkNumber = 0;

            while (true) {

                const { value, done } = await reader.read();

                if (done) {
                    break;
                }

                chunkNumber++;

                const text = decoder.decode(value, { stream: true });

                // 直接推送，不做攒批
                window.__doubao_sse_push(text);
            }

            const tail = decoder.decode();
            if (tail) {
                window.__doubao_sse_push(tail);
            }

            console.log("[COMPLETION_STREAM_END]", "chunks=" + chunkNumber);

        } catch (e) {
            console.log("[COMPLETION_CLONE_ERROR]", String(e));
        }

        return response;
    };

})();