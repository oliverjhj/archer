import { useEffect, useState } from 'react';

// The pages of the app, addressed by the URL fragment so each can be linked
// to directly (/#/how-it-was-built). The fragment never reaches the server,
// which serves the same app shell at / for all of them.
export type Route = 'ask' | 'how-to-use' | 'how-it-was-built' | 'make-your-own';

export const ROUTE_HASH: Record<Route, string> = {
  ask: '#/',
  'how-to-use': '#/how-to-use',
  'how-it-was-built': '#/how-it-was-built',
  'make-your-own': '#/make-your-own',
};

function routeFromHash(hash: string): Route {
  const name = hash.replace(/^#\/?/, '');
  return name === 'how-to-use' || name === 'how-it-was-built' || name === 'make-your-own'
    ? name
    : 'ask';
}

export function useHashRoute(): Route {
  const [route, setRoute] = useState<Route>(() => routeFromHash(window.location.hash));

  useEffect(() => {
    const onChange = () => setRoute(routeFromHash(window.location.hash));
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);

  return route;
}
