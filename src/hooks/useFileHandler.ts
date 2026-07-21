import { useState, useRef, useCallback } from "react";
import { useTranslation } from "react-i18next";
import {
  CHAT_UPLOAD_EXTENSIONS,
  CHAT_UPLOAD_MAX_FILES,
  CHAT_UPLOAD_MAX_TOTAL_BYTES,
  TEXT_FILE_EXTENSIONS,
  VALID_IMAGE_MIME_TYPES,
} from "../utils/constants";
import { showToast } from "../utils/toast";

const ALLOWED_UPLOAD_EXTENSIONS = new Set(CHAT_UPLOAD_EXTENSIONS);

const formatFileSize = (bytes, decimals = 2) => {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ["Bytes", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + " " + sizes[i];
};

export const useFileHandler = ({ enabled = true } = {}) => {
  const { t } = useTranslation();
  const [files, setFiles] = useState([]);
  const [, setDragCounter] = useState(0);
  const [isDragActive, setIsDragActive] = useState(false);
  const dragHasFilesRef = useRef(false);
  const fileInputRef = useRef(null);

  const isTextFile = (file) => {
    if (!file?.name) return false;
    const extension = file.name.split(".").pop()?.toLowerCase() || "";
    return (
      file.type.startsWith("text/") || TEXT_FILE_EXTENSIONS.includes(extension)
    );
  };

  const hasFileData = useCallback((event) => {
    const types = Array.from(event.dataTransfer?.types || []);
    if (types.includes("Files")) return true;
    const items = Array.from(event.dataTransfer?.items || []) as DataTransferItem[];
    return items.some((item) => item.kind === "file");
  }, []);

  const setOverlayState = useCallback((active) => {
    setIsDragActive(active);
    document.body.classList.toggle("drag-over", active);
  }, []);

  const addFiles = useCallback(
    (newFiles) => {
      if (!enabled) return;
      if (!newFiles || newFiles.length === 0) return;
      let fileList = Array.from(newFiles) as File[];

      const totalFiles = files.length + fileList.length;
      if (totalFiles > CHAT_UPLOAD_MAX_FILES) {
        showToast(t("files.tooMany", { count: CHAT_UPLOAD_MAX_FILES }), { type: "warning" });
        const remainingSlots = CHAT_UPLOAD_MAX_FILES - files.length;
        if (remainingSlots <= 0) return;
        fileList = fileList.slice(0, remainingSlots);
      }

      let totalBytes = files.reduce((sum, file) => sum + Number(file.size || 0), 0);
      const acceptedFiles: File[] = [];
      let showedTypeWarning = false;
      let showedSizeWarning = false;
      let showedEmptyWarning = false;

      for (const file of fileList) {
        const extension = file.name.split(".").pop()?.toLowerCase() || "";
        if (!ALLOWED_UPLOAD_EXTENSIONS.has(extension)) {
          if (!showedTypeWarning) {
            showToast(t("files.unsupportedType", { name: file.name }), { type: "warning" });
            showedTypeWarning = true;
          }
          continue;
        }
        if (file.size <= 0) {
          if (!showedEmptyWarning) {
            showToast(t("files.emptyFile", { name: file.name }), { type: "warning" });
            showedEmptyWarning = true;
          }
          continue;
        }
        if (totalBytes + file.size > CHAT_UPLOAD_MAX_TOTAL_BYTES) {
          if (!showedSizeWarning) {
            showToast(
              t("files.sizeLimit", {
                size: formatFileSize(CHAT_UPLOAD_MAX_TOTAL_BYTES, 0),
              }),
              { type: "warning" },
            );
            showedSizeWarning = true;
          }
          continue;
        }
        totalBytes += file.size;
        acceptedFiles.push(file);
      }

      if (acceptedFiles.length > 0) {
        setFiles((prev) => [...prev, ...acceptedFiles]);
      }
    },
    [enabled, files, t]
  );

  const removeFile = useCallback((index) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const clearFiles = useCallback(() => {
    setFiles([]);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }, []);

  const handleFileInputChange = useCallback(
    (e) => {
      if (!enabled) {
        return;
      }
      if (e.target.files) {
        addFiles(e.target.files);
      }
    },
    [addFiles, enabled]
  );

  const handleDragEnter = useCallback(
    (e) => {
      e.preventDefault();
      e.stopPropagation();

      if (!enabled) {
        return;
      }

      if (hasFileData(e)) {
        dragHasFilesRef.current = true;
      }

      setDragCounter((prev) => {
        const newCount = prev + 1;
        if (newCount === 1 && dragHasFilesRef.current) {
          setOverlayState(true);
        }
        return newCount;
      });
    },
    [enabled, hasFileData, setOverlayState]
  );

  const handleDragLeave = useCallback(
    (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (!enabled) {
        return;
      }
      setDragCounter((prev) => {
        const newCount = prev - 1;
        if (newCount <= 0) {
          dragHasFilesRef.current = false;
          setOverlayState(false);
          return 0;
        }
        return newCount;
      });
    },
    [enabled, setOverlayState]
  );

  const handleDragOver = useCallback(
    (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (!enabled) {
        return;
      }
      if (!isDragActive && hasFileData(e)) {
        dragHasFilesRef.current = true;
        setOverlayState(true);
      }
    },
    [enabled, hasFileData, isDragActive, setOverlayState]
  );

  const handleDrop = useCallback(
    (e) => {
      e.preventDefault();
      e.stopPropagation();
      dragHasFilesRef.current = false;
      setOverlayState(false);
      setDragCounter(0);
      if (!enabled) {
        return;
      }
      if (e.dataTransfer?.files) {
        addFiles(e.dataTransfer.files);
      }
    },
    [addFiles, enabled, setOverlayState]
  );

  return {
    files,
    isDragActive,
    fileInputRef,
    addFiles,
    removeFile,
    clearFiles,
    formatFileSize,
    isTextFile,
    handleFileInputChange,
    handleDragEnter,
    handleDragLeave,
    handleDragOver,
    handleDrop,
    MAX_FILES: CHAT_UPLOAD_MAX_FILES,
    VALID_IMAGE_MIME_TYPES,
  };
};
