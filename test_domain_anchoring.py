"""Anchoring test for clearance_filter's .gov.<cc> rule (adversarial lookalikes)."""
import clearance_filter as cf
def domain_ok(host):
    res = cf.Result(); cf.check_domain({"host": host}, res); return res.checks[0][1]
CASES = {"www.contractsfinder.service.gov.uk":True,"contractsfinder.service.gov.uk":True,
  "www.ms.gov":True,"data.gov.au":True,"notgov.uk":False,"gov.uk.evil.com":False,
  "foo-gov.uk":False,"evilgov.uk":False,"contractsfinder.service.gov.uk.attacker.com":False,
  "demandstar.com":False}
if __name__=="__main__":
    bad=[h for h,w in CASES.items() if domain_ok(h)!=w]
    print("ANCHORING:", "ALL PASS" if not bad else f"FAIL {bad}"); assert not bad
