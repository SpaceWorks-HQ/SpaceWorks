export type Availability =
  | null
  | {
      mode: "status_only" | "exact_count";
      label?: "Available" | "Limited" | "Unavailable";
      count?: number;
    };

export type Product = {
  id: number;
  name: string;
  description: string;
  borrowing_terms?: string;
  category_id?: number | null;
  category_name?: string | null;
  category_slug?: string | null;
  tracking_mode?: "quantity" | "individual";
  availability: Availability;
  image_url?: string | null;
};

export type PublicCategory = {
  id: number;
  name: string;
  slug: string;
  display_order: number;
  icon: string;
  product_count: number;
};

export type Makerspace = {
  name: string;
  public_code: string;
  slug: string;
  location: string;
  map_url?: string;
  logo_url?: string | null;
  cover_image_url?: string | null;
};

export type PaginatedResponse<T> = {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
};

export type RequestCartItem = {
  productId: number;
  name: string;
  quantity: number;
};

export type RequestSubmitResponse = {
  public_token: string;
  status: string;
};

export type PublicRequestStatus = {
  public_token?: string;
  requested_for?: string;
  status: string;
  rejection_reason: string;
  created_at: string;
  items: {
    product_name: string;
    requested_quantity: number;
  }[];
};

export type PublicToolLoan = {
  public_token: string;
  status: string;
  items: {
    product_name: string;
    quantity: number;
  }[];
};

