const unavailable = () => {
    throw new Error('Node.js file-system APIs are not available in the browser bundle.');
};

export const readFileSync = unavailable;
export const dirname = unavailable;
export const basename = unavailable;
export const join = unavailable;

export default {
    readFileSync,
    dirname,
    basename,
    join,
};
