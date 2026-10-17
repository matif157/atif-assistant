package ai.atif.assistant;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

/**
 * Foreground service that keeps the app process - and with it the embedded
 * Python engine and its loopback server - alive while the app is backgrounded.
 *
 * The ongoing notification is deliberately quiet (IMPORTANCE_MIN): it exists
 * to satisfy the foreground-service contract, not to notify anyone. Without
 * it Android would freeze the engine within minutes of the user leaving the
 * app, and chat-over-network plus reminder delivery would stop.
 */
public class EngineService extends Service {

    private static final String CHANNEL_ID = "engine";
    private static final int NOTIFICATION_ID = 1001;

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
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        return START_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null; // started only, never bound
    }
}
