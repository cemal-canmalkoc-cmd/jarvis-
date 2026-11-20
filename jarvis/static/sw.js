// Jarvis Service Worker: zeigt Push-Mitteilungen an und öffnet die App beim Antippen.
self.addEventListener("push", (event) => {
  let data = {title: "Jarvis", body: "", url: "/app"};
  try { data = Object.assign(data, event.data.json()); } catch (e) { if (event.data) data.body = event.data.text(); }
  event.waitUntil(self.registration.showNotification(data.title, {
    body: data.body, icon: "/app/icon-180.png", badge: "/app/icon-180.png", data: {url: data.url},
  }));
});
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/app";
  event.waitUntil(clients.matchAll({type: "window", includeUncontrolled: true}).then((list) => {
    for (const c of list) { if ("focus" in c) { c.navigate(url); return c.focus(); } }
    return clients.openWindow(url);
  }));
});
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(clients.claim()));
