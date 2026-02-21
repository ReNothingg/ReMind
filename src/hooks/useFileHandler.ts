import { useState, useRef, useCallback } from "react";
import {
  TEXT_FILE_EXTENSIONS,
  VALID_IMAGE_MIME_TYPES,
  VALID_3D_MODEL_EXTENSIONS,
  VALID_3D_MODEL_MIME_TYPES,
} from "../utils/constants";

const MAX_FILES = 10;

export const useFileHandler = () => {
  const [files, setFiles] = useState([]);
  const [dragCounter, setDragCounter] = useState(0); // Используется для отслеживания вложенных drag событий
  const [isDragActive, setIsDragActive] = useState(false);
  const dragHasFilesRef = useRef(false);
  const fileInputRef = useRef(null);

  const formatFileSize = (bytes, decimals = 2) => {
    if (bytes === 0) return "0 Bytes";
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ["Bytes", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + " " + sizes[i];
  };

  const isTextFile = (file) => {
    if (!file?.name) return false;
    const extension = file.name.split(".").pop()?.toLowerCase() || "";
    return (
      file.type.startsWith("text/") || TEXT_FILE_EXTENSIONS.includes(extension)
    );
  };

  const is3DModelFile = (file) => {
    if (!file?.name) return false;
    const extension = file.name.split(".").pop()?.toLowerCase() || "";
    return (
      VALID_3D_MODEL_EXTENSIONS.includes(extension) ||
      VALID_3D_MODEL_MIME_TYPES.includes(file.type)
    );
  };

  const hasFileData = useCallback((event) => {
    const types = Array.from(event.dataTransfer?.types || []);
    if (types.includes("Files")) return true;
    const items = Array.from(event.dataTransfer?.items || []);
    return items.some((item) => item.kind === "file");
  }, []);

  const setOverlayState = useCallback((active) => {
    setIsDragActive(active);
    document.body.classList.toggle("drag-over", active);
  }, []);

  const addFiles = useCallback(
    (newFiles) => {
      if (!newFiles || newFiles.length === 0) return;
      let fileList = Array.from(newFiles);

      const totalFiles = files.length + fileList.length;
      if (totalFiles > MAX_FILES) {
        alert(`Можно прикрепить не более ${MAX_FILES} файлов.`);
        const remainingSlots = MAX_FILES - files.length;
        if (remainingSlots <= 0) return;
        fileList = fileList.slice(0, remainingSlots);
      }

      setFiles((prev) => [...prev, ...fileList]);
    },
    [files.length]
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
      if (e.target.files) {
        addFiles(e.target.files);
      }
    },
    [addFiles]
  );

  const handleDragEnter = useCallback(
    (e) => {
      e.preventDefault();
      e.stopPropagation();

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
    [hasFileData, setOverlayState]
  );

  const handleDragLeave = useCallback(
    (e) => {
      e.preventDefault();
      e.stopPropagation();
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
    [setOverlayState]
  );

  const handleDragOver = useCallback(
    (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (!isDragActive && hasFileData(e)) {
        dragHasFilesRef.current = true;
        setOverlayState(true);
      }
    },
    [hasFileData, isDragActive, setOverlayState]
  );

  const handleDrop = useCallback(
    (e) => {
      e.preventDefault();
      e.stopPropagation();
      dragHasFilesRef.current = false;
      setOverlayState(false);
      setDragCounter(0);
      if (e.dataTransfer?.files) {
        addFiles(e.dataTransfer.files);
      }
    },
    [addFiles, setOverlayState]
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
    is3DModelFile,
    handleFileInputChange,
    handleDragEnter,
    handleDragLeave,
    handleDragOver,
    handleDrop,
    MAX_FILES,
    VALID_IMAGE_MIME_TYPES,
    VALID_3D_MODEL_EXTENSIONS,
    VALID_3D_MODEL_MIME_TYPES,
  };
};
