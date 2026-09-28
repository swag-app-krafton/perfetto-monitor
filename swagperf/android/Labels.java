import android.content.Context;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;

/**
 * Prints `<package>\t<name>` for every non-system app on the phone: the name
 * the phone shows under the app's icon. `pm list packages` gives package ids
 * only, so swagperf pushes this (built to labels.dex by build.sh) to
 * /data/local/tmp and runs it with app_process, which asks Android's own
 * PackageManager (capture.app_labels).
 */
public class Labels {
    public static void main(String[] args) throws Exception {
        android.os.Looper.prepareMainLooper();
        Class<?> at = Class.forName("android.app.ActivityThread");
        Object thread = at.getMethod("systemMain").invoke(null);
        Context ctx = (Context) at.getMethod("getSystemContext").invoke(thread);
        PackageManager pm = ctx.getPackageManager();
        for (ApplicationInfo ai : pm.getInstalledApplications(0)) {
            if ((ai.flags & ApplicationInfo.FLAG_SYSTEM) != 0) continue;
            try {
                String name = String.valueOf(pm.getApplicationLabel(ai)).replaceAll("[\\t\\r\\n]+", " ").trim();
                System.out.println(ai.packageName + "\t" + name);
            } catch (RuntimeException e) {
                // One app's broken resources never cost the others their names.
            }
        }
    }
}
