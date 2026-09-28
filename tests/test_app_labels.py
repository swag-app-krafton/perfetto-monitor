"""App names from the phone (F-031): the name each app shows on the phone,
read through Android's PackageManager by swagperf/android/Labels.java, and
used wherever the dashboard would otherwise show a package id."""
import json, os, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from swagperf import capture, catalogue


class TestParse(unittest.TestCase):

    def test_reads_package_and_name_per_line(self):
        out = ("com.phonepe.app\tPhonePe\r\n"
               "money.super.payments\tsuper.money\n"
               "\n"
               "not a label line\n"
               "com.nameless.app\tcom.nameless.app\n"
               "com.blank.app\t \n")
        self.assertEqual(capture.parse_labels(out),
                         {"com.phonepe.app": "PhonePe", "money.super.payments": "super.money"})


class TestAskOnce(unittest.TestCase):

    def setUp(self):
        capture._LABELS.clear()

    def test_the_phone_is_asked_once_per_package(self):
        phone = {"com.phonepe.app": "PhonePe", "in.gov.umang": "UMANG"}
        reads = []

        def read(serial):
            reads.append(serial)
            return dict(phone)
        with mock.patch.object(capture, "devices", return_value=["S1"]), \
                mock.patch.object(capture, "_read_labels", side_effect=read):
            self.assertEqual(capture.app_labels(["com.phonepe.app", "com.unknown"]), {"com.phonepe.app": "PhonePe"})
            # A poll with the same apps asks nothing, even for the one with no name,
            # and an app the phone already named comes from that same answer.
            capture.app_labels(["com.phonepe.app", "com.unknown"])
            self.assertEqual(capture.app_labels(["in.gov.umang"]), {"in.gov.umang": "UMANG"})
            self.assertEqual(reads, ["S1"])
            # An app installed since then asks again.
            phone["net.one97.paytm"] = "Paytm"
            self.assertEqual(capture.app_labels(["net.one97.paytm"]), {"net.one97.paytm": "Paytm"})
            self.assertEqual(reads, ["S1", "S1"])

    def test_no_phone_no_names(self):
        with mock.patch.object(capture, "devices", return_value=[]):
            self.assertEqual(capture.app_labels(["com.phonepe.app"]), {})


class TestCatalogueNames(unittest.TestCase):

    def setUp(self):
        self.orig = catalogue.USER
        self.tmp = tempfile.mkdtemp()
        catalogue.USER = os.path.join(self.tmp, "apps.local.json")
        catalogue.save_user([
            {"pkg": "com.auto.app", "name": "com.auto.app", "role": "competitor", "auto": True},
            {"pkg": "com.named.app", "name": "Named by a person", "role": "competitor"},
        ])

    def tearDown(self):
        catalogue.USER = self.orig

    def test_placeholders_take_the_phones_name_and_names_people_set_stay(self):
        n = catalogue.adopt_names({"com.auto.app": "Auto App", "com.named.app": "Phone's name",
                                   "com.swag.pay": "Something else"})
        self.assertEqual(n, 1)
        self.assertEqual(catalogue.display("com.auto.app"), "Auto App")
        self.assertEqual(catalogue.display("com.named.app"), "Named by a person")
        self.assertEqual(catalogue.display("com.swag.pay"), "Swag Pay")
        # Still a placeholder: a name from the phone never overrides a built-in entry.
        auto = next(a for a in json.load(open(catalogue.USER))["apps"] if a["pkg"] == "com.auto.app")
        self.assertTrue(auto["auto"])

    def test_nothing_to_adopt_writes_nothing(self):
        catalogue.adopt_names({"com.auto.app": "Auto App"})
        before = os.path.getmtime(catalogue.USER)
        os.utime(catalogue.USER, (before - 100, before - 100))
        self.assertEqual(catalogue.adopt_names({"com.auto.app": "Auto App"}), 0)
        self.assertEqual(os.path.getmtime(catalogue.USER), before - 100)


class TestDeviceList(unittest.TestCase):

    def setUp(self):
        self.orig = catalogue.USER
        catalogue.USER = os.path.join(tempfile.mkdtemp(), "apps.local.json")

    def tearDown(self):
        catalogue.USER = self.orig

    def test_installed_apps_show_their_names(self):
        from swagperf import server
        patches = [
            mock.patch.object(capture, "device_info", return_value={"serial": "S1", "model": "V2514"}),
            mock.patch.object(capture, "installed_packages", return_value=["com.example.labelled", "com.swag.pay", "com.zzz.nameless"]),
            mock.patch.object(capture, "app_labels", return_value={"com.example.labelled": "Labelled App", "com.swag.pay": "Swag Pay Debug"}),
            mock.patch("swagperf.flashlight.runner_status", return_value={}),
            mock.patch.object(capture, "device_health", return_value={}),
            mock.patch.object(capture, "devices", return_value=["S1"]),
            mock.patch.object(capture, "other_profilers", return_value=[]),
            mock.patch.object(capture, "manual_status", return_value={"recording": False}),
        ]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        rows = {r["pkg"]: r for r in server._device_payload("android")["packages"] if r["installed"]}
        self.assertEqual(rows["com.example.labelled"]["name"], "Labelled App")   # not in the catalogue: the phone's name
        self.assertEqual(rows["com.swag.pay"]["name"], "Swag Pay")          # the catalogue's name wins
        self.assertEqual(rows["com.zzz.nameless"]["name"], "com.zzz.nameless")


class TestNewPlaceholders(unittest.TestCase):

    def setUp(self):
        self.orig = catalogue.USER
        catalogue.USER = os.path.join(tempfile.mkdtemp(), "apps.local.json")

    def tearDown(self):
        catalogue.USER = self.orig

    def test_a_capture_of_an_unknown_app_records_its_name(self):
        from swagperf import jobs
        with mock.patch.object(capture, "app_labels", return_value={"com.example.labelled": "Labelled App"}):
            jobs._add_placeholder("com.example.labelled", "android")
            jobs._add_placeholder("com.zzz.nameless", "android")
        self.assertEqual(catalogue.display("com.example.labelled"), "Labelled App")
        self.assertEqual(catalogue.display("com.zzz.nameless"), "com.zzz.nameless")
        self.assertTrue(catalogue.get("com.example.labelled")["auto"])


if __name__ == "__main__":
    unittest.main()
