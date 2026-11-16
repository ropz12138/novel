package com.liyicheng.novel;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.media.MediaMetadata;
import android.media.session.MediaSession;
import android.media.session.PlaybackState;
import android.os.Build;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

@CapacitorPlugin(name = "AudiobookMedia")
public class AudiobookMediaPlugin extends Plugin {
    private static final String CHANNEL = "audiobook";
    private static final int NOTIFICATION_ID = 1101;
    private static AudiobookMediaPlugin instance;
    private MediaSession session;
    private boolean playing;

    @Override
    public void load() {
        instance = this;
        session = new MediaSession(getContext(), "NovelAudiobook");
        session.setCallback(new MediaSession.Callback() {
            @Override public void onPlay() { if (!playing) toggle(); }
            @Override public void onPause() { if (playing) toggle(); }
        });
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            getContext().getSystemService(NotificationManager.class).createNotificationChannel(
                new NotificationChannel(CHANNEL, "有声小说", NotificationManager.IMPORTANCE_LOW));
        }
    }

    private void toggle() {
        notifyListeners("toggle", new JSObject(), true);
    }

    public static class ActionReceiver extends BroadcastReceiver {
        @Override public void onReceive(Context context, Intent intent) {
            if (instance != null) instance.toggle();
        }
    }

    @PluginMethod
    public void update(PluginCall call) {
        String title = call.getString("title", "有声小说");
        playing = Boolean.TRUE.equals(call.getBoolean("playing"));
        session.setMetadata(new MediaMetadata.Builder().putString(MediaMetadata.METADATA_KEY_TITLE, title).build());
        session.setPlaybackState(new PlaybackState.Builder()
            .setActions(PlaybackState.ACTION_PLAY | PlaybackState.ACTION_PAUSE)
            .setState(playing ? PlaybackState.STATE_PLAYING : PlaybackState.STATE_PAUSED, PlaybackState.PLAYBACK_POSITION_UNKNOWN, 1f)
            .build());
        session.setActive(true);
        Intent actionIntent = new Intent(getContext(), ActionReceiver.class);
        PendingIntent action = PendingIntent.getBroadcast(getContext(), 0, actionIntent, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Intent openIntent = new Intent(getContext(), MainActivity.class);
        PendingIntent open = PendingIntent.getActivity(getContext(), 0, openIntent, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder builder = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
            ? new Notification.Builder(getContext(), CHANNEL) : new Notification.Builder(getContext());
        Notification notification = builder.setSmallIcon(android.R.drawable.ic_media_play)
            .setContentTitle(title).setContentText("有声小说")
            .setContentIntent(open).setOnlyAlertOnce(true).setVisibility(Notification.VISIBILITY_PUBLIC)
            .addAction(playing ? android.R.drawable.ic_media_pause : android.R.drawable.ic_media_play,
                playing ? "暂停" : "播放", action)
            .setStyle(new Notification.MediaStyle().setMediaSession(session.getSessionToken()).setShowActionsInCompactView(0))
            .build();
        getContext().getSystemService(NotificationManager.class).notify(NOTIFICATION_ID, notification);
        call.resolve();
    }

    @PluginMethod
    public void clear(PluginCall call) {
        getContext().getSystemService(NotificationManager.class).cancel(NOTIFICATION_ID);
        session.setActive(false);
        call.resolve();
    }

    @Override
    protected void handleOnDestroy() {
        getContext().getSystemService(NotificationManager.class).cancel(NOTIFICATION_ID);
        session.release();
        instance = null;
    }
}
