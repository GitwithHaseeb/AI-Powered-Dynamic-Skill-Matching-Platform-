import React from 'react';
import useCountUp from '../../hooks/useCountUp.js';

/** Counts up to `value`; renders non-numeric values as-is. */
const AnimatedNumber = ({ value, prefix = '', suffix = '', duration }) => {
  const shown = useCountUp(value, duration);
  return (
    <span className="tabular-nums">
      {prefix}
      {shown}
      {suffix}
    </span>
  );
};

export default AnimatedNumber;
