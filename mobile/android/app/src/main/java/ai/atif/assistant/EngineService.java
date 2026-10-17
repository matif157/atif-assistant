package ai.atif.assistant;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.IBinder;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * Foreground service that keeps the app process - and with it the embedded
 * Python engine and its loopback server - alive while the app is backgrounded.
 *
 * The ongoing notification is deliberately quiet (IMPORTANCE_MIN): it exists
 * to satisfy the foreground-service contract, not to notify anyone. Without
 * it Android would freeze the engine within minutes of the user leaving the
 * app, and chat-over-network plus reminder delivery would stop.
 *
 * Phase 8c: also polls the server's undelivered auto-drafts and surfaces
 * each one as a notification, because the WebView's JS does not run while
 * the app is backgrounded - this thread does.
 */
public class EngineService extends Service {

    private static final String CHANNEL_ID = "engine";
    private static final int NOTIFICATION_ID = 1001;
    private static final String DRAFTS_CHANNEL_ID = "drafts";
    private static final long POLL_MS = 20_000L;

    private volatile boolean stopped = false;
    private Thread poller;

    @Override
    public void onCreate() {
        super.onCreate();
        NotificationManager nm = getSystemService(NotificationManager.class);
        Notification.Builder builder;
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL_ID, "Engine",
                    NotificationManager.IMPORTANCE_MIN);
            channel.setDescription(
                    "Keeps the offline assistant engine running");
            nm.createNotificationChannel(channel);
            builder = new Notification.Builder(this, CHANNEL_ID);
        } else {
            builder = new Notification.Builder(this);
        }
        Notification n = builder
                .setSmallIcon(R.mipmap.ic_launcher)
                .setContentTitle("Atif Assistant")
                .setContentText("Offline engine running in the background")
                .setOngoing(true)
                .build();
        startForeground(NOTIFICATION_ID, n);
        ensureDraftsChannel(nm);
        startDraftPoller();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        return START_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null; // started only, never bound
    }

    @Override
    public void onDestroy() {
        stopped = true;
        if (poller != null) {
            poller.interrupt();
        }
        super.onDestroy();
    }

    private void ensureDraftsChannel(NotificationManager nm) {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel channel = new NotificationChannel(
                    DRAFTS_CHANNEL_ID, "Suggested replies",
                    NotificationManager.IMPORTANCE_HIGH);
            channel.setDescription(
                    "Draft WhatsApp replies prepared for you to copy");
            nm.createNotificationChannel(channel);
        }
    }

    private void startDraftPoller() {
        poller = new Thread(() -> {
            while (!stopped && !Thread.currentThread().isInterrupted()) {
                try {
                    pollDrafts();
                } catch (Throwable t) {
                    android.util.Log.w("Atif", "draft poll failed", t);
                }
                try {
                    Thread.sleep(POLL_MS);
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    return;
                }
            }
        }, "atif-drafts");
        poller.setDaemon(true);
        poller.start();
    }

    private void pollDrafts() {
        HttpURLConnection c = null;
        String body = null;
        try {
            c = (HttpURLConnection) new URL(
                    "http://127.0.0.1:8770/api/inbox/drafts").openConnection();
            c.setConnectTimeout(3000);
            c.setReadTimeout(3000);
            c.setRequestMethod("GET");
            int code = c.getResponseCode();
            if (code < 200 || code >= 300) {
                return;
            }
            InputStream in = c.getInputStream();
            byte[] buf = new byte[8192];
            StringBuilder sb = new StringBuilder();
            int n;
            while ((n = in.read(buf)) > 0) {
                sb.append(new String(buf, 0, n, StandardCharsets.UTF_8));
            }
            body = sb.toString();
        } catch (Exception e) {
            return; // server still booting or shutting down; retried next tick
        } finally {
            if (c != null) {
                c.disconnect();
            }
        }
        try {
            JSONArray items = new JSONObject(body).optJSONArray("items");
            if (items == null) {
                return;
            }
            for (int i = 0; i < items.length(); i++) {
                JSONObject it = items.optJSONObject(i);
                if (it != null) {
                    deliverDraft(it);
                }
            }
        } catch (Exception e) {
            android.util.Log.w("Atif", "draft parse failed", e);
        }
    }

    private void deliverDraft(JSONObject item) {
        int id = item.optInt("id", -1);
        String chat = item.optString("chat", "WhatsApp");
        String draft = item.optString("draft", "");
        if (id < 0 || draft.isEmpty()) {
            return;
        }
        boolean allowed = Build.VERSION.SDK_INT < 33 || checkSelfPermission(
                Manifest.permission.POST_NOTIFICATIONS)
                == PackageManager.PERMISSION_GRANTED;
        if (allowed) {
            NotificationManager nm = getSystemService(NotificationManager.class);
            Intent open = new Intent(this, MainActivity.class);
            open.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
            PendingIntent pi = PendingIntent.getActivity(
                    this, 2000 + id, open,
                    PendingIntent.FLAG_UPDATE_CURRENT
                            | PendingIntent.FLAG_IMMUTABLE);
            Notification.Builder builder;
            if (Build.VERSION.SDK_INT >= 26) {
                builder = new Notification.Builder(this, DRAFTS_CHANNEL_ID);
            } else {
                builder = new Notification.Builder(this);
            }
            Notification n = builder
                    .setSmallIcon(R.mipmap.ic_launcher)
                    .setContentTitle("Draft for " + chat)
                    .setContentText(draft)
                    .setStyle(new Notification.BigTextStyle().bigText(draft))
                    .setContentIntent(pi)
                    .setAutoCancel(true)
                    .build();
            nm.notify(2000 + id, n);
        }
        // Mark delivered so the same draft never reappears; when permission
        // is missing the row stays pending and surfaces once it is granted.
        if (allowed) {
            markNotified(id);
        }
    }

    private void markNotified(int inboxId) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(
                    "http://127.0.0.1:8770/api/inbox/" + inboxId + "/notified")
                    .openConnection();
            c.setConnectTimeout(1500);
            c.setReadTimeout(1500);
            c.setRequestMethod("POST");
            c.setDoOutput(true);
            c.getResponseCode();
        } catch (Exception ignored) {
            // stays pending; the next poll retries the whole delivery
        } finally {
            if (c != null) {
                c.disconnect();
            }
        }
    }
}
