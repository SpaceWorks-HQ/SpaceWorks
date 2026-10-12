import type {
  MakerspaceForm,
  ResetPasswordForm,
  RestrictForm,
  StaffForm,
} from "../UsersModals";

export const emptyStaffForm: StaffForm = {
  username: "",
  email: "",
  first_name: "",
  last_name: "",
  password: "",
  role_id: "",
  makerspace_id: "",
};
export const emptyRestrictForm: RestrictForm = { status: "restricted", reason: "" };
export const emptyMakerspaceForm: MakerspaceForm = {
  name: "",
  public_code: "",
  slug: "",
  location: "",
  superadmin_access_enabled: true,
};
export const emptyResetPasswordForm: ResetPasswordForm = { password: "" };

export function staffPayload(form: StaffForm) {
  return {
    username: form.username.trim(),
    email: form.email.trim(),
    first_name: form.first_name.trim(),
    last_name: form.last_name.trim(),
    password: form.password,
    role_id: Number(form.role_id),
  };
}

export function makerspacePayload(form: MakerspaceForm) {
  return {
    creation_setup: {
      ...(form.profile ? { profile: form.profile } : {}),
      ...(form.modules ? { modules: form.modules } : {}),
      ...(form.first_staff_email?.trim() ? { first_staff_invite: { email: form.first_staff_email.trim(), role_slug: form.first_staff_role ?? "space_manager" } } : {}),
    },
    ...(form.install_profile_id ? { install_profile_id: form.install_profile_id } : {}),
    name: form.name.trim(),
    public_code: form.public_code.trim(),
    slug: form.slug.trim(),
    location: form.location.trim(),
    superadmin_access_enabled: form.superadmin_access_enabled,
  };
}
