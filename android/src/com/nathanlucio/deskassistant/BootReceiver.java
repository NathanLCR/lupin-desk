package com.nathanlucio.deskassistant;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;

/**
 * Starts the kiosk shell on boot or when USB power is connected, only if the user enabled it
 * in the server menu. Off by default. Newer Android versions may block background activity
 * starts; there the shell simply stays closed until opened by hand.
 */
public class BootReceiver extends BroadcastReceiver {

    @Override
    public void onReceive(Context context, Intent intent) {
        if (context == null || intent == null || intent.getAction() == null) {
            return;
        }
        String action = intent.getAction();
        if (!Intent.ACTION_BOOT_COMPLETED.equals(action)
                && !Intent.ACTION_POWER_CONNECTED.equals(action)) {
            return;
        }
        SharedPreferences prefs = context.getSharedPreferences(
                MainActivity.PREFS_NAME, Context.MODE_PRIVATE);
        if (!prefs.getBoolean(MainActivity.KEY_START_ON_BOOT, false)) {
            return;
        }
        Intent launch = new Intent(context, MainActivity.class);
        launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            context.startActivity(launch);
        } catch (RuntimeException ignored) {
            // Background start blocked by the OS: nothing else to do.
        }
    }
}
