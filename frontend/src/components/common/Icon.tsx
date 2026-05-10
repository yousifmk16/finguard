interface IconProps {
  name: string;
  size?: number;
}

export default function Icon({ name, size = 16 }: IconProps) {
  const props = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.6,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  switch (name) {
    case "dashboard":
      return (<svg {...props}><rect x="3" y="3" width="7" height="9"/><rect x="14" y="3" width="7" height="5"/><rect x="14" y="12" width="7" height="9"/><rect x="3" y="16" width="7" height="5"/></svg>);
    case "alert":
      return (<svg {...props}><path d="M12 3l9 16H3z"/><path d="M12 10v4"/><circle cx="12" cy="17" r="0.8" fill="currentColor"/></svg>);
    case "bell":
      return (<svg {...props}><path d="M6 8a6 6 0 0 1 12 0c0 7 3 7 3 9H3c0-2 3-2 3-9z"/><path d="M10 20a2 2 0 0 0 4 0"/></svg>);
    case "shield":
      return (<svg {...props}><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/></svg>);
    case "settings":
      return (<svg {...props}><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>);
    case "search":
      return (<svg {...props}><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>);
    case "filter":
      return (<svg {...props}><path d="M3 5h18M6 12h12M10 19h4"/></svg>);
    case "chevron-left":
      return (<svg {...props}><path d="M15 18l-6-6 6-6"/></svg>);
    case "chevron-right":
      return (<svg {...props}><path d="M9 18l6-6-6-6"/></svg>);
    case "x":
      return (<svg {...props}><path d="M18 6L6 18M6 6l12 12"/></svg>);
    case "check":
      return (<svg {...props}><path d="M5 13l4 4L19 7"/></svg>);
    case "clock":
      return (<svg {...props}><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>);
    case "logs":
      return (<svg {...props}><path d="M4 6h16M4 12h16M4 18h10"/></svg>);
    case "users":
      return (<svg {...props}><circle cx="9" cy="8" r="3"/><path d="M3 20a6 6 0 0 1 12 0"/><circle cx="17" cy="9" r="2.5"/><path d="M15 20a4.5 4.5 0 0 1 6 0"/></svg>);
    case "play":
      return (<svg {...props}><path d="M6 4l14 8-14 8z"/></svg>);
    case "menu":
      return (<svg {...props}><path d="M3 6h18M3 12h18M3 18h18"/></svg>);
    case "share":
      return (<svg {...props}><path d="M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7"/><path d="M16 6l-4-4-4 4"/><path d="M12 2v14"/></svg>);
    case "sparkles":
      return (<svg {...props}><path d="M12 3l1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5z"/></svg>);
    case "policy":
      return (<svg {...props}><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 9h8M8 13h8M8 17h5"/></svg>);
    case "audit":
      return (<svg {...props}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M9 13h6M9 17h4"/></svg>);
    case "ext":
      return (<svg {...props}><path d="M14 4h6v6"/><path d="M20 4l-8 8"/><path d="M19 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h5"/></svg>);
    case "log-out":
      return (<svg {...props}><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/></svg>);
    case "trash":
      return (<svg {...props}><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/></svg>);
    default:
      return null;
  }
}
