export type MakerspaceRef = {
  id: number;
};

export type HandoverRequestItem = {
  id: number;
  product_name: string;
  tracking_mode: string;
  accepted_quantity: number;
  issued_quantity: number;
  returned_quantity: number;
  damaged_quantity: number;
  missing_quantity: number;
};

export type HandoverRequest = {
  id: number;
  assigned_box_code?: string | null;
  items: HandoverRequestItem[];
};

export type DialogProps = {
  row: HandoverRequest;
  makerspace: MakerspaceRef;
  onClose: () => void;
};

export type ReturnValues = {
  returned: string;
  damaged: string;
  missing: string;
};

export type ReturnField = keyof ReturnValues;
