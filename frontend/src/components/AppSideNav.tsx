import type { MouseEvent } from 'react';
import {
  SideNav,
  SideNavDivider,
  SideNavItems,
  SideNavLink,
} from '@carbon/react';
import { Chat, Help, Information } from '@carbon/icons-react';

const REPO_URL = 'https://github.com/oliverjhj/archer';

interface AppSideNavProps {
  onOpenGuide: () => void;
}

// Primary side navigation (IBM Carbon UI Shell).
//
// Every item here does something: a link that goes nowhere makes the whole
// interface read as a mockup.
export function AppSideNav({ onOpenGuide }: AppSideNavProps) {
  return (
    <SideNav
      aria-label="Primary navigation"
      isFixedNav
      expanded
      isChildOfHeader={false}
    >
      <SideNavItems>
        <SideNavLink renderIcon={Chat} href="#" isActive>
          Ask
        </SideNavLink>
        <SideNavLink
          renderIcon={Information}
          href="#"
          onClick={(event: MouseEvent) => {
            event.preventDefault();
            onOpenGuide();
          }}
        >
          How to use Archer
        </SideNavLink>
        <SideNavDivider />
        <SideNavLink
          renderIcon={Help}
          href={REPO_URL}
          target="_blank"
          rel="noopener noreferrer"
        >
          Source and docs
        </SideNavLink>
      </SideNavItems>
    </SideNav>
  );
}
