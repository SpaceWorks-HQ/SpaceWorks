import type { StaffAuthUser } from "../../lib/api";
import type { Makerspace } from "./panels/shared";
import { Users, EmailTemplatesPanel, EmailLogPanel, ApiClientsPanel, PlatformEmailPanel, PlatformUpdatePanel, PlatformStripeConnectPanel, PlatformSocialAuthPanel, MakerspaceSettingsPanel, ModulesPanel, DataExportsPanel, BackupRestorePanel, TenantMigrationPanel } from "./StaffTabLoaders";

export function StaffPlatformTabContent({ activeTab, activeMakerspace, makerspaces, isSuperadmin, canManageMakerspace, currentUser, onAuthRefresh }: { activeTab: string; activeMakerspace: Makerspace; makerspaces: Makerspace[]; isSuperadmin: boolean; canManageMakerspace: boolean; currentUser: StaffAuthUser; onAuthRefresh: () => void }) {
  const makerspaceKey = activeMakerspace.id;
  return <>
      {activeTab === "api" ? (
        <ApiClientsPanel
          key={makerspaceKey}
          makerspace={activeMakerspace}
          isSuperadmin={isSuperadmin}
          canManageMakerspace={canManageMakerspace}
        />
      ) : null}
      {activeTab === "settings" ? (
        <MakerspaceSettingsPanel
          key={makerspaceKey}
          makerspace={activeMakerspace}
          isSuperadmin={isSuperadmin}
          canManageMakerspace={canManageMakerspace}
        />
      ) : null}
      {activeTab === "emailtemplates" ? (
        <EmailTemplatesPanel key={makerspaceKey} makerspace={activeMakerspace} />
      ) : null}
      {activeTab === "email-logs" && canManageMakerspace ? (
        <EmailLogPanel key={makerspaceKey} makerspace={activeMakerspace} />
      ) : null}
      {activeTab === "modules" && isSuperadmin ? (
        <ModulesPanel key={makerspaceKey} makerspaceId={activeMakerspace.id} />
      ) : null}
      {activeTab === "platform" ? (
        <>
          <PlatformUpdatePanel />
          <PlatformEmailPanel />
          <PlatformSocialAuthPanel />
          {activeMakerspace.platform_hosting ? <PlatformStripeConnectPanel /> : null}
        </>
      ) : null}
      {activeTab === "users" && canManageMakerspace ? (
        <Users makerspaces={makerspaces} isSuperadmin={isSuperadmin} currentUser={currentUser} onAuthRefresh={onAuthRefresh} />
      ) : null}
      {activeTab === "exports" && canManageMakerspace ? (
        <DataExportsPanel key={makerspaceKey} makerspaceId={makerspaceKey} />
      ) : null}
      {activeTab === "backups" && canManageMakerspace ? (
        <BackupRestorePanel key={makerspaceKey} makerspaceId={makerspaceKey} isSuperadmin={isSuperadmin} tenantBackupsEnabled={activeMakerspace?.enabled_modules?.includes("backup") ?? false} />
      ) : null}
      {activeTab === "migration" && isSuperadmin ? (
        <TenantMigrationPanel key={makerspaceKey} makerspace={activeMakerspace} />
      ) : null}
  </>;
}
