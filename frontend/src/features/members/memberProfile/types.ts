export type MemberProject = {
  id: number;
  title: string;
  description: string;
  links: { label: string; url: string }[];
  image_url: string | null;
};

export interface MemberProfileActivity {
  events_attended?: number;
  events_registered?: number;
  recent_attended_events?: { id: number; title: string; starts_at: string }[];
}

export type MemberProfile = {
  membership_id: number;
  display_name: string;
  is_visible: boolean;
  show_attended_events: boolean;
  headline: string;
  institution: string;
  bio: string;
  avatar_url: string | null;
  interests: string[];
  languages: string[];
  education: { institution: string; qualification?: string; year?: string }[];
  github_username: string;
  github_contributions: number | null;
  projects: MemberProject[];
  activity: MemberProfileActivity;
};

export type ProjectDraft = {
  id?: number;
  title: string;
  description: string;
  links: { label: string; url: string }[];
};
