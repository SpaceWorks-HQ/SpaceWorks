import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { bootstrapTenant, refreshAccessToken } from "../../lib/api";
import { hasClaimSession } from "./MemberClaimSession";
import { MemberAuthPanel } from "./MemberAuthPanel";
import { MemberAccountProfile } from "./MemberAccountProfile";
import { MemberAccountSessions } from "./MemberAccountSessions";
import { MemberAccountMembership } from "./MemberAccountMembership";
import { MemberAccountExports } from "./MemberAccountExports";

export function MemberAccountPage() {
  const { slug = "" } = useParams();
  const [restoring, setRestoring] = useState(true);
  const [signIn, setSignIn] = useState(false);
  const [left, setLeft] = useState(false);
  const client = useQueryClient();
  useEffect(() => { setLeft(false); }, [slug]);
  useEffect(() => {
    let active = true;
    void (async () => {
      await client.cancelQueries({ queryKey: ["member", "account"] });
      client.removeQueries({ queryKey: ["member", "account"] });
      const token = await refreshAccessToken();
      if (active) { setSignIn(!token); setRestoring(false); }
    })().catch(() => { if (active) { setSignIn(true); setRestoring(false); } });
    return () => { active = false; };
  }, [client]);
  const authenticated = async () => {
    await client.cancelQueries({ queryKey: ["member"] });
    client.removeQueries({ queryKey: ["member"] });
    setLeft(false);
    setSignIn(false);
  };
  const bootstrap = useQuery({ queryKey: ["member", slug, "bootstrap"], queryFn: () => bootstrapTenant({ slug: slug || undefined }), retry: false });
  const data = bootstrap.data;
  const selfService = data?.modules?.includes("membership") && data.modules?.includes("member_accounts") && data.features?.includes("membership.self_service");
  const selfExport = data?.modules?.includes("membership") && data.modules?.includes("member_accounts") && data.features?.includes("membership.self_export");
  const home = slug ? `/m/${slug}/member` : "/member";
  if (signIn && !restoring) return <MemberAuthPanel makerspaceSlug={slug} onAuthenticated={() => { void authenticated(); }} />;
  return <main className="mx-auto max-w-3xl space-y-5 px-5 py-8"><Link className="desk-button" to={home}>Back to membership</Link><h1 className="title-page">Your account</h1>
    {restoring || bootstrap.isLoading ? <p role="status">Loading account…</p> : null}
    {bootstrap.error ? <p className="text-danger" role="alert">{bootstrap.error.message}</p> : null}
    {left ? <p role="status">You have left this makerspace. Your account remains available.</p> : null}
    {!restoring && hasClaimSession() ? <p>Sign in with a full account to manage profile, sessions or exports.</p> : null}
    {!restoring && data && !hasClaimSession() && !left ? <>
      {!selfService && !selfExport ? <p>Account self-service is disabled for this makerspace.</p> : null}
      {selfService ? <><MemberAccountProfile key={`profile-${data.makerspace.id}`} makerspaceId={data.makerspace.id} /><MemberAccountSessions key={`sessions-${data.makerspace.id}`} makerspaceId={data.makerspace.id} onSignedOut={() => setSignIn(true)} /><MemberAccountMembership key={`membership-${data.makerspace.id}`} makerspaceId={data.makerspace.id} onLeft={() => setLeft(true)} /></> : null}
      {selfExport ? <MemberAccountExports key={`exports-${data.makerspace.id}`} makerspaceId={data.makerspace.id} /> : null}
    </> : null}
  </main>;
}
