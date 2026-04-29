# -*- coding: utf-8 -*-
from Products.Five import BrowserView
from Products.CMFCore.utils import getToolByName

try:
    from bika.lims import api, logger
except Exception:
    api = None
    import logging
    logger = logging.getLogger("senaite.impress")

import re
import unicodedata
import datetime
import time


# ------------------ Compatibilidad Py2/Py3 ------------------
try:
    unicode
except NameError:
    unicode = str

try:
    long
except NameError:
    long = int


# ------------------ Helpers ------------------
def _u(v):
    try:
        return unicode(v)
    except Exception:
        try:
            return u"%s" % v
        except Exception:
            return u""


def _strip_accents(s):
    try:
        s = _u(s)
        return u"".join(
            c for c in unicodedata.normalize("NFD", s)
            if unicodedata.category(c) != "Mn"
        )
    except Exception:
        return _u(s)


def _to_num(x):
    try:
        if x in (None, u"", ""):
            return None

        if isinstance(x, (int, float, long)):
            return float(x)

        s = _u(x)
        s = s.replace("<", "").replace(">", "")
        s = s.replace(",", ".")
        return float(s)
    except Exception:
        return None


def _norm(s):
    return u" ".join(_u(s).strip().lower().split()) if s else u""


# ============================================================
class InfolabsaDeltaCheck(BrowserView):

    PERIOD_DAYS = 365
    MAX_POINTS = 8
    STATES_OK = set(("verified", "to_be_published", "published", "verified_duplicate"))

    # ------------------ SAFE GET ------------------
    def _get(self, obj, name, default=None):
        if not obj:
            return default
        attr = getattr(obj, name, None)
        try:
            return attr() if callable(attr) else attr
        except Exception:
            return default

    # ------------------ FECHAS ------------------
    def _iso(self, dt):
        if not dt:
            return u""
        try:
            if api:
                return api.to_datetime(dt).strftime("%Y-%m-%dT%H:%M:%S")
            return dt.ISO8601().replace("Z", "")
        except Exception:
            return _u(dt)

    def _to_epoch_ms(self, iso):
        try:
            clean = _u(iso).replace("Z", "").split("+")[0]

            if "T" in clean:
                dt = datetime.datetime.strptime(clean, "%Y-%m-%dT%H:%M:%S")
            else:
                dt = datetime.datetime.strptime(clean, "%Y-%m-%d")

            return int(time.mktime(dt.timetuple()) * 1000)
        except Exception:
            return None

    # ------------------ RESULTADO ------------------
    def _result_value(self, a):
        for g in ("getResult", "Result", "result", "getValue"):
            v = self._get(a, g)
            if v not in (None, u"", ""):
                num = _to_num(v)
                if num is not None:
                    return _u(v), float(num)

        fr = self._get(a, "getFormattedResult")
        if fr:
            s = _u(fr)

            m = re.search(r'[-<>]?\s*\d+(?:[.,]\d+)?', s)
            if m:
                num = _to_num(m.group(0))
                if num is not None:
                    return s, float(num)

            sn = _norm(_strip_accents(s))

            if any(k in sn for k in ("negativo", "no detectado")):
                return s, 0.0
            if any(k in sn for k in ("positivo", "detectado")):
                return s, 1.0

        return u"—", None

    # ------------------ SERIES ------------------
    def _series_for_uid(self, ars, uid):
        pts = []

        for ar in ars:
            for a in self._get(ar, "getAnalyses", []):
                svc_uid = self._get(a, "getServiceUID")

                if svc_uid != uid:
                    continue

                raw, val = self._result_value(a)
                if val is None:
                    continue

                dt = self._get(ar, "getDateReceived") or self._get(ar, "created")
                if not dt:
                    continue

                iso = self._iso(dt)

                pts.append({
                    "date": iso,
                    "value": float(val),
                    "ms": self._to_epoch_ms(iso)
                })

        pts.sort(key=lambda x: x["date"])
        return pts[-self.MAX_POINTS:]

    # ------------------ MAIN ------------------
    def __call__(self):

        ar = self.context
        analyses = self._get(ar, "getAnalyses", [])

        rows = []
        multi_series = []

        for a in analyses:

            uid = self._get(a, "getServiceUID")
            name = self._get(a, "Title")
            unit = self._get(a, "getUnit") or u""

            raw_now, val_now = self._result_value(a)

            series = self._series_for_uid([ar], uid)

            if len(series) < 2:
                continue

            # DELTA SIMPLE
            prev = series[-2]["value"]
            curr = series[-1]["value"]

            delta = curr - prev

            pct = (delta / prev * 100.0) if prev else 0

            rows.append({
                "name": _u(name),
                "unit": _u(unit),
                "value_now": raw_now,
                "delta": round(pct, 2),
            })

            multi_series.append({
                "name": _u(name),
                "data": [[p["ms"], p["value"]] for p in series if p["ms"]],
            })

        return {
            "rows": rows,
            "chart": {
                "series": multi_series
            },
            "has_chart": bool(multi_series)
        }
