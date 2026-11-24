import { useState, useEffect, useCallback } from 'react';

export const useURLRouter = () => {
  const [hash, setHash] = useState(() => {
    return window.location.hash.slice(1);
  });
  const [queryParams, setQueryParams] = useState(() => {
    return new URLSearchParams(window.location.search);
  });
  const parseURL = useCallback(() => {
    const newHash = window.location.hash.slice(1);
    const newQueryParams = new URLSearchParams(window.location.search);
    setHash(newHash);
    setQueryParams(newQueryParams);
  }, []);
  useEffect(() => {
    const handleHashChange = () => {
      parseURL();
      window.dispatchEvent(
        new CustomEvent('hashRouteChange', {
          detail: {
            hash: window.location.hash.slice(1),
            queryParams: new URLSearchParams(window.location.search),
          },
        })
      );
    };

    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, [parseURL]);
  const getHashParts = useCallback(() => {
    if (!hash) return [];
    return hash.split('/').filter((part) => part);
  }, [hash]);
  const isSettingsView = useCallback(() => {
    const parts = getHashParts();
    return parts.length > 0 && parts[0] === 'settings';
  }, [getHashParts]);
  const getSettingsTab = useCallback(() => {
    return getHashParts()[1]?.toLowerCase() ?? null;
  }, [getHashParts]);
  const getQueryParam = useCallback(
    (key: string) => {
      return queryParams.get(key);
    },
    [queryParams]
  );
  const getAllQueryParams = useCallback(() => {
    const result: Record<string, string> = {};
    queryParams.forEach((value, key) => {
      result[key] = value;
    });
    return result;
  }, [queryParams]);
  const navigate = useCallback(
    (newHash: string, replaceHistory = false) => {
      if (replaceHistory) {
        const url = new URL(window.location.href);
        url.hash = newHash;
        window.history.replaceState(window.history.state, '', url);
        window.dispatchEvent(new Event('hashchange'));
      } else {
        window.location.hash = newHash;
      }
      parseURL();
    },
    [parseURL]
  );
  const navigateToSettings = useCallback(
    (tab = 'appearance', replaceHistory = false) => {
      navigate(`settings/${tab}`, replaceHistory);
    },
    [navigate]
  );
  const updateQueryParams = useCallback(
    (params: Record<string, string | number | boolean | null | undefined>) => {
      const newParams = new URLSearchParams(queryParams);
      Object.entries(params).forEach(([key, value]) => {
        if (value === null || value === undefined) {
          newParams.delete(key);
        } else {
          newParams.set(key, String(value));
        }
      });

      const newSearch = newParams.toString();
      const newURL = `${window.location.pathname}${newSearch ? '?' + newSearch : ''}${window.location.hash}`;
      window.history.replaceState(null, '', newURL);
      parseURL();
    },
    [queryParams, parseURL]
  );
  const clearQueryParams = useCallback(() => {
    const newURL = `${window.location.pathname}${window.location.hash}`;
    window.history.replaceState(null, '', newURL);
    parseURL();
  }, [parseURL]);
  const hasQueryParam = useCallback(
    (key: string) => {
      return queryParams.has(key);
    },
    [queryParams]
  );
  const clearHash = useCallback(() => {
    window.history.replaceState(null, '', window.location.pathname + window.location.search);
    parseURL();
  }, [parseURL]);

  return {
    hash,
    queryParams,
    getHashParts,
    isSettingsView,
    getSettingsTab,
    getQueryParam,
    getAllQueryParams,
    navigate,
    navigateToSettings,
    updateQueryParams,
    clearQueryParams,
    hasQueryParam,
    clearHash,
  };
};
