// Thin re-export barrel. The implementation lives in ./machinesApi/*; every existing
// `import { X } from ".../machinesApi"` keeps resolving through here.
export type {
  Machine,
  MachineAccessLevel,
  MachineCollection,
  MachineDocument,
  MachineErrorLog,
  MachineListResponse,
  MachineOperator,
  MachineOperatorCandidate,
  MachinePatch,
  MachinePayload,
  MachinePublicPreview,
  MachineStatus,
  MachineType,
  MachineTypeCapabilityConfig,
  MachineUsageEntry,
  MachineWarrantyStatus,
  MeteringUnit,
} from "./machinesApi/types";

export {
  collectionResults,
  machineKeys,
  machinePublicPreviewKey,
} from "./machinesApi/keys";

export {
  createMachineType,
  getMachineTypePricing,
  getMachineTypes,
  isBuiltinPrinterType,
  setMachineTypePricing,
  updateMachineType,
} from "./machinesApi/machineTypes";

export {
  createMachine,
  deleteMachineImage,
  getMachine,
  getMachinePublicPreview,
  getMachines,
  machineImageEndpoint,
  retireMachine,
  setMachinePublicity,
  setMachineStatus,
  unretireMachine,
  updateMachine,
  uploadMachineImage,
} from "./machinesApi/machines";

export {
  addMachineErrorLog,
  addMachineOperator,
  addMachineUsage,
  deleteMachineOperator,
  getMachineErrorLogs,
  getMachineOperators,
  getMachineUsage,
  getOperatorCandidates,
  updateMachineOperator,
} from "./machinesApi/logs";

export {
  getConsumableCandidates,
  getMachineConsumables,
  linkMachineConsumable,
  logMachineConsumption,
  unlinkMachineConsumable,
  type ConsumableCandidate,
  type ConsumableMeasurement,
  type LinkConsumablePayload,
  type MachineConsumable,
} from "./machineConsumablesApi";

export {
  deleteMachineDocument,
  getMachineDocuments,
  getMachineDocumentUrl,
  uploadMachineDocument,
} from './machineDocumentsApi';
