package com.myhomecinema.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;
import android.util.Log;

/**
 * Foreground service that owns the My Home Cinema HTTP server, so Android
 * does not kill sharing as soon as you leave the app to watch on TV.
 */
public class SharingService extends Service {

    public static final String ACTION_START = "com.myhomecinema.app.START";
    public static final String ACTION_STOP = "com.myhomecinema.app.STOP";

    public static boolean running = false;
    public static String currentUrl = null;
    public static String currentFolder = null;

    private HomeCinemaServer server = null;

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            stopSharing();
            stopSelf();
            return START_NOT_STICKY;
        }
        if (intent == null) return START_STICKY;

        String folder = intent.getStringExtra("folder");
        if (folder == null || folder.isEmpty()) folder = "/storage/emulated/0/Movies";
        int port = intent.getIntExtra("port", 8000);
        currentFolder = folder;

        try {
            if (server != null) server.stop();
            server = new HomeCinemaServer(getApplicationContext(), folder, port);
            server.start();
            String ip = HomeCinemaServer.getLocalIp();
            currentUrl = "http://" + ip + ":" + port;
            running = true;

            Notification notification = buildNotification(currentUrl);
            startForeground(1, notification);
            Log.i("My Home Cinema", "Sharing at " + currentUrl + " from " + folder);
        } catch (Exception e) {
            Log.e("My Home Cinema", "Failed to start server", e);
            running = false;
            currentUrl = null;
            stopSelf();
        }
        return START_STICKY;
    }

    private Notification buildNotification(String url) {
        String channelId = "myhomecinema_sharing";
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26 && nm != null) {
            NotificationChannel ch = new NotificationChannel(
                    channelId, "My Home Cinema sharing",
                    NotificationManager.IMPORTANCE_LOW);
            ch.setDescription("My Home Cinema is sharing your movies over Wi-Fi");
            nm.createNotificationChannel(ch);
        }
        Notification.Builder b;
        if (Build.VERSION.SDK_INT >= 26) {
            b = new Notification.Builder(this, channelId);
        } else {
            b = new Notification.Builder(this);
        }
        return b.setContentTitle("My Home Cinema sharing")
                .setContentText("Open on your TV: " + url)
                .setSmallIcon(android.R.drawable.ic_media_play)
                .setOngoing(true)
                .build();
    }

    private void stopSharing() {
        try {
            if (server != null) server.stop();
        } catch (Exception ignored) {
        }
        server = null;
        running = false;
        currentUrl = null;
        currentFolder = null;
        stopForeground(true);
    }

    @Override
    public void onDestroy() {
        stopSharing();
        super.onDestroy();
    }
}
