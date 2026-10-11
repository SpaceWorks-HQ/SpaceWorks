import { createContext } from "react";

export const StaffListContext = createContext<{ ownerName: string; canShare: boolean; actions?: readonly string[]; isSuperadmin?: boolean }>({ ownerName: "", canShare: false });
