import type { CustomFormSchema } from "../forms/customFormTypes";

export type EventTicket = {
  id: number; name: string; amount: string; audience: "member" | "public";
  spots_left: number | null;
};

export type PublicEventDetail = {
  public_token: string; title: string; description: string;
  starts_at: string; ends_at: string; location: string;
  capacity: number | null; payment_amount: string; currency: string;
  availability: "Available" | "Limited" | "Full";
  registration_audience?: "members" | "accounts" | "invite";
  ticket_types?: EventTicket[]; ticket_selection_required?: boolean; promo_codes_enabled?: boolean;
  category?: { id: number; name: string; slug: string } | null; tags?: string[];
  registration_requires_approval: boolean;
  effective_registration_cutoff_at: string | null; registration_open: boolean;
  image_url: string | null; status: "published"; custom_form: CustomFormSchema;
  series: { public_token: string; title: string } | null;
};
