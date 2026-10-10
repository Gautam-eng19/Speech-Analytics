import { createClient } from '@/api/client';
import { settingsStore } from '@/lib/settings';

/** The one API client of the app. Its base URL follows the settings (empty = same origin). */
export const api = createClient(() => settingsStore.get().apiBase);
