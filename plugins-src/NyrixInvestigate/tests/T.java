import dev.nyrix.investigate.NyrixInvestigate;
import dev.nyrix.investigate.NyrixInvestigate.*;
import java.util.UUID;
public class T {
  static int fail=0;
  static void eq(Object a,Object b,String n){ boolean ok=String.valueOf(a).equals(String.valueOf(b)); System.out.println((ok?"PASS ":"FAIL ")+n+" -> "+a); if(!ok)fail++; }
  public static void main(String[] x){
    UUID inv=UUID.randomUUID(), other=UUID.randomUUID(), owner=UUID.randomUUID();
    Case c=new Case(); c.id="C1"; c.status="UNDER_INVESTIGATION"; c.claimerUuid=inv.toString();
    eq(NyrixInvestigate.decide(c,inv,owner),Verdict.OK,"assigned investigator allowed");
    eq(NyrixInvestigate.decide(c,other,owner),Verdict.NOT_YOURS,"other staff blocked (can't steal)");
    eq(NyrixInvestigate.decide(c,owner,owner),Verdict.OK,"owner override");
    eq(NyrixInvestigate.decide(null,inv,owner),Verdict.NO_CASE,"missing case");
    Case u=new Case(); u.id="C2"; u.status="UNCLAIMED";
    eq(NyrixInvestigate.decide(u,inv,owner),Verdict.NOT_CLAIMED,"unclaimed blocked for staff");
    Case cl=new Case(); cl.id="C3"; cl.status="CLOSED"; cl.claimerUuid=inv.toString();
    eq(NyrixInvestigate.decide(cl,inv,owner),Verdict.CLOSED,"closed case blocked for investigator");
    eq(NyrixInvestigate.decide(cl,owner,owner),Verdict.CLOSED,"closed case blocked for owner too");
    Case rel=new Case(); rel.id="C4"; rel.status="UNDER_INVESTIGATION"; rel.claimerUuid=null;
    eq(NyrixInvestigate.decide(rel,inv,owner),Verdict.NOT_CLAIMED,"released case blocked");
    eq(NyrixInvestigate.decide(c,inv,null),Verdict.OK,"owner not resolved: investigator still ok");
    eq(NyrixInvestigate.parse("/sus investigate C12"),"C12","parse basic");
    eq(NyrixInvestigate.parse("/SUS Investigate c12"),"c12","parse case-insensitive");
    eq(NyrixInvestigate.parse("/nyrixbadges:sus investigate C1"),"C1","parse namespaced bypass");
    eq(NyrixInvestigate.parse("/suspects investigate C1"),"C1","parse alias");
    eq(NyrixInvestigate.parse("/sus investigate"),"","parse missing id");
    eq(NyrixInvestigate.parse("/sus SomePlayer"),null,"normal /sus untouched");
    eq(NyrixInvestigate.parse("/sus stop"),null,"/sus stop untouched");
    System.out.println(fail==0?"ALL PASSED":"FAILURES: "+fail);
  }
}
