package ai.atif.assistant;

import android.app.Notification;
import android.os.Bundle;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;

import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Phase 8 live reader: watches WhatsApp notifications through the official
 * notification-access API (no root, no ToS games) and forwards each new
 * message to the embedded server's /api/inbox/whatsapp.
 *
 * The OS only exposes what a notification shows - a live feed of incoming
 * messages, not full history (history comes from chat exports). Delivery is
 * retried with backoff because the Python server may still be booting when
 * the first message of a cold start arrives; after four failures the message
 * is dropped rather than stalling the listener thread.
 */
public class MessageListenerService extends NotificationListenerService {

    private ExecutorService io;

    @Override
    public void onCreate() {
        super.onCreate();
        io = Executors.newSingleThreadExecutor();
    }

    @Override
    public void onNotificationPosted(StatusBarNotification sbn) {
        if (sbn == null) {
            return;
        }
        String pkg = sbn.getPackageName();
        if (!"com.whatsapp".equals(pkg) && !"com.whatsapp.w4b".equals(pkg)) {
            return;
        }
        Notification n = sbn.getNotification();
        if (n == null || n.extras == null) {
            return;
        }
        Bundle ex = n.extras;
        CharSequence title = ex.getCharSequence(Notification.EXTRA_TITLE);
        CharSequence text = ex.getCharSequence(Notification.EXTRA_TEXT);
        if (text == null) {
            text = ex.getCharSequence(Notification.EXTRA_BIG_TEXT);
        }
        if (text == null || text.length() == 0) {
            return;
        }
        final String chat = title == null ? "unknown" : title.toString();
        final String body = text.toString();
        final long when = n.when;
        final String packageName = pkg;
        if (io == null) {
            io = Executors.newSingleThreadExecutor();
        }
        io.execute(() -> deliver(packageName, chat, body, when));
    }

    private void deliver(String pkg, String chat, String body, long when) {
        byte[] payload;
        try {
            JSONObject j = new JSONObject();
            j.put("package", pkg);
            j.put("chat", chat);
            j.put("text", body);
            j.put("post_time", when);
            payload = j.toString().getBytes(StandardCharsets.UTF_8);
        } catch (Exception e) {
            return;
        }
        for (int attempt = 0; attempt < 4; attempt++) {
            HttpURLConnection c = null;
            try {
                c = (HttpURLConnection) new URL(
                        "http://127.0.0.1:8770/api/inbox/whatsapp")
                        .openConnection();
                c.setConnectTimeout(1500);
                c.setReadTimeout(1500);
                c.setRequestMethod("POST");
                c.setRequestProperty("Content-Type", "application/json");
                c.setDoOutput(true);
                try (OutputStream os = c.getOutputStream()) {
                    os.write(payload);
                }
                int code = c.getResponseCode();
                if (code >= 200 && code < 300) {
                    return;
                }
            } catch (Exception ignored) {
                // server still booting, or gone - retried below
            } finally {
                if (c != null) {
                    c.disconnect();
                }
            }
            try {
                Thread.sleep(1000L * (attempt + 1));
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                return;
            }
        }
    }

    @Override
    public void onDestroy() {
        if (io != null) {
            io.shutdown();
        }
        super.onDestroy();
    }
}
