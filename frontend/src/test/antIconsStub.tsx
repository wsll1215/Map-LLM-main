import { createElement } from "react";

function icon(name: string) {
  return function StubIcon() {
    return createElement("span", { "aria-hidden": true, "data-icon": name });
  };
}

export const ApartmentOutlined = icon("ApartmentOutlined");
export const BranchesOutlined = icon("BranchesOutlined");
export const BulbOutlined = icon("BulbOutlined");
export const CheckCircleFilled = icon("CheckCircleFilled");
export const CloudDownloadOutlined = icon("CloudDownloadOutlined");
export const CloseCircleFilled = icon("CloseCircleFilled");
export const CopyOutlined = icon("CopyOutlined");
export const DatabaseOutlined = icon("DatabaseOutlined");
export const DownOutlined = icon("DownOutlined");
export const EyeOutlined = icon("EyeOutlined");
export const FilterOutlined = icon("FilterOutlined");
export const LoadingOutlined = icon("LoadingOutlined");
export const PictureOutlined = icon("PictureOutlined");
export const ReloadOutlined = icon("ReloadOutlined");
export const RightOutlined = icon("RightOutlined");
export const RobotOutlined = icon("RobotOutlined");
export const SafetyCertificateOutlined = icon("SafetyCertificateOutlined");
export const ToolOutlined = icon("ToolOutlined");
export const WarningOutlined = icon("WarningOutlined");
