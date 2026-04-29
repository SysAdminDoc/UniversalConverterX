/*! coi-serviceworker v0.1.7 - Guido Zuidhof and contributors, licensed under MIT */
// This service worker adds COOP/COEP headers to enable SharedArrayBuffer
// Required for ffmpeg.wasm multi-threaded support

self.addEventListener("install", () => {
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
    const request = event.request;
    
    if (request.cache === "only-if-cached" && request.mode !== "same-origin") {
        return;
    }

    event.respondWith(
        fetch(request)
            .then((response) => {
                if (response.status === 0) {
                    return response;
                }

                const newHeaders = new Headers(response.headers);
                // credentialless allows loading cross-origin resources from CDNs
                newHeaders.set("Cross-Origin-Embedder-Policy", "credentialless");
                newHeaders.set("Cross-Origin-Opener-Policy", "same-origin");

                return new Response(response.body, {
                    status: response.status,
                    statusText: response.statusText,
                    headers: newHeaders,
                });
            })
            .catch((error) => {
                console.error("Service worker fetch error:", error);
                throw error;
            })
    );
});

self.addEventListener("message", (event) => {
    if (event.data && event.data.type === "deregister") {
        self.registration
            .unregister()
            .then(() => self.clients.matchAll())
            .then((clients) => {
                clients.forEach((client) => client.navigate(client.url));
            });
    }
});
